// Voximplant VoxEngine сценарий для AI-звонаря VoiceAgentа.
// Заливается в Voximplant Console как scenario, привязывается к application + rule.
//
// Логика:
//   1) callPSTN по customData.phone (international11)
//   2) Слушаем клиента (ASR) → POST /zvonar/dialogue/turn
//   3) Бэкенд возвращает {reply_text, audio_url, outcome?, hangup?}
//   4) Воспроизводим audio_url, цикл до outcome|hangup|max_turns|fail
//   5) reportFinish → /zvonar/dialogue/finish с outcome
//
// Перед заливкой в Voximplant Console заменить %%SHARED_TOKEN%% на
// значение SECRET_KEY из /opt/voiceagent/.env (не коммитить в git).
//
// Ошибки классифицируются по docs/TELEPHONY_FAILURES.md (13 классов).
// Каждый failure_class попадает в reportFinish и далее в dashboard/zvonar.

const BACKEND_URL = "https://voiceagent.example.com";
const SHARED_TOKEN = "%%SHARED_TOKEN%%";

const MAX_TURNS = 12;
const ASR_TIMEOUT_MS = 8000;
const PLAY_TIMEOUT_MS = 30000;
const HTTP_TIMEOUT_MS = 6000;

require(Modules.ASR);
require(Modules.Player);

VoxEngine.addEventListener(AppEvents.Started, async (e) => {
  const data = safeParse(e.scriptCustomData) || {};
  const sessionId = VoxEngine.sessionId();
  Logger.write("zvonar.start session_id=" + sessionId + " lead_id=" + data.lead_id);

  let call;
  try {
    call = VoxEngine.callPSTN(data.phone, "Olimp AI");
  } catch (err) {
    await reportFinish(data.lead_id, sessionId, "no_answer", "scenario_crash", err.message);
    VoxEngine.terminate();
    return;
  }

  call.addEventListener(CallEvents.Connected, async () => {
    Logger.write("zvonar.connected session_id=" + sessionId);
    try {
      await runDialogLoop(call, data.lead_id, sessionId);
    } catch (err) {
      Logger.write("zvonar.loop_crash " + err.message);
      await reportFinish(data.lead_id, sessionId, "error", "scenario_crash", err.message);
    } finally {
      try { call.hangup(); } catch (_) {}
    }
  });

  call.addEventListener(CallEvents.Failed, async (ev) => {
    const failureClass = mapVoxCallFailure(ev.code, ev.reason);
    Logger.write("zvonar.failed code=" + ev.code + " class=" + failureClass);
    await reportFinish(data.lead_id, sessionId, mapOutcome(failureClass), failureClass, ev.reason);
    VoxEngine.terminate();
  });

  call.addEventListener(CallEvents.Disconnected, () => {
    Logger.write("zvonar.disconnected session_id=" + sessionId);
    VoxEngine.terminate();
  });
});


async function runDialogLoop(call, leadId, sessionId) {
  let outcome = "no_answer";
  let lastFailureClass = null;
  for (let turn = 0; turn < MAX_TURNS; turn++) {
    let userSpeech = "";
    try {
      userSpeech = await listenOnce(call);
    } catch (err) {
      lastFailureClass = "stt_fail";
      Logger.write("zvonar.asr_fail turn=" + turn + " err=" + err.message);
      break;
    }

    let reply;
    try {
      reply = await fetchTurn(leadId, sessionId, turn, userSpeech);
    } catch (err) {
      lastFailureClass = err.failureClass || "llm_fail";
      Logger.write("zvonar.backend_fail turn=" + turn + " class=" + lastFailureClass);
      break;
    }

    if (reply.audio_url) {
      try {
        await play(call, reply.audio_url);
      } catch (err) {
        lastFailureClass = "streaming_drop";
        Logger.write("zvonar.play_fail turn=" + turn + " err=" + err.message);
        break;
      }
    }

    if (reply.outcome) { outcome = reply.outcome; break; }
    if (reply.hangup)  { outcome = reply.outcome || outcome; break; }
  }

  await reportFinish(leadId, sessionId, outcome, lastFailureClass, null);
}


function listenOnce(call) {
  return new Promise((resolve, reject) => {
    let asr;
    try {
      asr = VoxEngine.createASR({ profile: ASRProfileList.Default, recognitionMode: "Long" });
    } catch (err) {
      reject(err); return;
    }
    call.sendMediaTo(asr);

    let done = false;
    const finish = (text) => {
      if (done) return; done = true;
      try { asr.stop(); } catch (_) {}
      resolve(text);
    };

    asr.addEventListener(ASREvents.Result, (e) => finish(e.text || ""));
    asr.addEventListener(ASREvents.SpeechCaptured, () => {});
    setTimeout(() => finish(""), ASR_TIMEOUT_MS);
  });
}


function play(call, url) {
  return new Promise((resolve, reject) => {
    let p;
    try { p = call.startPlayback(url); } catch (err) { reject(err); return; }
    let done = false;
    const finish = () => { if (done) return; done = true; resolve(); };
    p.addEventListener(PlayerEvents.PlaybackFinished, finish);
    p.addEventListener(PlayerEvents.PlaybackError, () => {
      done = true; reject(new Error("playback_error"));
    });
    setTimeout(finish, PLAY_TIMEOUT_MS);
  });
}


async function fetchTurn(leadId, sessionId, turn, userSpeech) {
  const r = await Net.httpRequestAsync(BACKEND_URL + "/zvonar/dialogue/turn", {
    method: "POST",
    timeout: HTTP_TIMEOUT_MS,
    headers: ["Content-Type: application/json", "X-Token: " + SHARED_TOKEN],
    postData: JSON.stringify({ lead_id: leadId, session_id: sessionId, turn, user_speech: userSpeech })
  });
  if (r.code >= 500) {
    const err = new Error("backend " + r.code);
    err.failureClass = "llm_fail";
    throw err;
  }
  if (r.code === 429) {
    const err = new Error("backend rate limit");
    err.failureClass = "crm_rate_limit";
    throw err;
  }
  if (r.code >= 400) {
    const err = new Error("backend " + r.code);
    err.failureClass = "scenario_crash";
    throw err;
  }
  return safeParse(r.text) || {};
}


async function reportFinish(leadId, sessionId, outcome, failureClass, errorText) {
  try {
    await Net.httpRequestAsync(BACKEND_URL + "/zvonar/dialogue/finish", {
      method: "POST",
      timeout: HTTP_TIMEOUT_MS,
      headers: ["Content-Type: application/json", "X-Token: " + SHARED_TOKEN],
      postData: JSON.stringify({
        lead_id: leadId,
        session_id: sessionId,
        outcome: outcome,
        failure_class: failureClass,
        error: errorText
      })
    });
  } catch (err) {
    Logger.write("zvonar.report_finish_fail err=" + err.message);
  }
}


// Voximplant CallEvents.Failed → класс из TELEPHONY_FAILURES.md.
// Коды Voximplant — см. https://voximplant.com/docs/references/voxengine/callevents
function mapVoxCallFailure(code, reason) {
  if (code === 486) return "busy";
  if (code === 480) return "no_answer";  // Temporarily Unavailable
  if (code === 408) return "no_answer";  // Request Timeout
  if (code === 487) return "no_answer";  // Cancelled
  if (code === 503) return "spam_block"; // Service Unavailable, often blocking
  if (code === 603) return "spam_block"; // Decline
  if (code === 404) return "spam_block"; // Number not found / blocked
  if (code === 401 || code === 407) return "scenario_crash"; // Auth issue → SIP-trunk
  return "no_answer";
}


function mapOutcome(failureClass) {
  if (!failureClass) return "no_answer";
  if (failureClass === "voicemail") return "no_answer";
  if (failureClass === "busy")      return "callback";
  if (failureClass === "spam_block") return "error";
  return "no_answer";
}


function safeParse(text) {
  try { return JSON.parse(text || "{}"); } catch (_) { return null; }
}
