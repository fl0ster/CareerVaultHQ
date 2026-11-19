/**
 * CareerVaultHQ - Gmail rejection monitor bridge.
 *
 * Deploy as a web app (Deploy > New deployment > Web app):
 *   Execute as: Me    Who has access: Anyone
 * and paste the /exec URL into CareerVaultHQ > Settings > Gmail monitor.
 *
 * Every request must carry the secret below; anything else is refused. The script decides
 * what can be read, not the caller: it searches only unread inbox mails of the last
 * MAX_LOOKBACK_DAYS days without the label, and returns only those that look like job
 * application mails (and not like password resets or sign-in codes). So even someone who
 * learns the secret cannot search the rest of the mailbox.
 */
const SECRET = '__CAREERVAULT_SECRET__';
const MAX_BODY_CHARS = 8000;
const MAX_LOOKBACK_DAYS = 30;
const MAX_MESSAGES = 50;
const LABEL_PATTERN = /^[\w .\/-]{1,128}$/;

/** At least one of these must appear in the subject or body (English and Polish). */
const JOB_WORDS = [
  'application', 'applied', 'applying', 'candidate', 'candidacy', 'position', 'role',
  'vacancy', 'recruit', 'hiring', 'interview', 'opportunity', 'job', 'talent', 'resume', 'cv',
  'aplikac', 'aplikow', 'kandyda', 'rekrutac', 'stanowisk', 'ofert', 'zgłoszeni', 'zgloszeni',
  'rozmow', 'prac',
];
/** Mails mentioning any of these are never returned. */
const SENSITIVE_WORDS = [
  'password', 'passcode', 'verification code', 'security code', 'one-time', 'one time code',
  '2-step', 'two-factor', '2fa', 'sign-in attempt', 'login attempt', 'confirm your email',
  'hasło', 'hasla', 'hasła', 'kod weryfikacyjny', 'kod jednorazowy', 'kod bezpieczeństwa',
];

function doPost(e) {
  try {
    const request = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    if (!SECRET || request.token !== SECRET) {
      return reply_({ error: 'unauthorized' });
    }
    switch (request.action) {
      case 'ping':
        return reply_({ email: Session.getEffectiveUser().getEmail() });
      case 'list':
        return reply_({ messages: listMessages_(request.lookback_days, request.label, request.max) });
      case 'mark':
        markMessage_(request.id, request.label);
        return reply_({ ok: true });
      default:
        return reply_({ error: 'unknown action: ' + request.action });
    }
  } catch (err) {
    return reply_({ error: String(err && err.message ? err.message : err) });
  }
}

function doGet() {
  return reply_({ error: 'use POST' });
}

function searchQuery_(lookbackDays, labelName) {
  const days = Math.max(1, Math.min(Math.floor(Number(lookbackDays) || 7), MAX_LOOKBACK_DAYS));
  let query = 'in:inbox is:unread newer_than:' + days + 'd';
  if (labelName) query += ' -label:' + checkLabel_(labelName).replace(/[\s\/]+/g, '-');
  return query;
}

function checkLabel_(labelName) {
  const label = String(labelName);
  if (!LABEL_PATTERN.test(label)) throw new Error('invalid label name');
  return label;
}

function containsAny_(text, words) {
  return words.some(function (word) {
    return text.indexOf(word) !== -1;
  });
}

function isJobMail_(subject, body) {
  const text = (subject + '\n' + body).toLowerCase();
  return containsAny_(text, JOB_WORDS) && !containsAny_(text, SENSITIVE_WORDS);
}

function listMessages_(lookbackDays, labelName, max) {
  const limit = Math.max(1, Math.min(Math.floor(Number(max) || 30), MAX_MESSAGES));
  const threads = GmailApp.search(searchQuery_(lookbackDays, labelName), 0, limit);
  const out = [];
  for (const thread of threads) {
    for (const message of thread.getMessages()) {
      if (!message.isUnread() || !message.isInInbox()) continue;
      const subject = message.getSubject() || '';
      const body = message.getPlainBody() || '';
      if (!isJobMail_(subject, body)) continue;
      out.push({
        id: message.getId(),
        thread_id: thread.getId(),
        from: message.getFrom(),
        subject: subject,
        date: message.getDate().toISOString(),
        body: body.slice(0, MAX_BODY_CHARS),
      });
      if (out.length >= limit) return out;
    }
  }
  return out;
}

function markMessage_(id, labelName) {
  const message = GmailApp.getMessageById(String(id));
  if (!message) throw new Error('message not found: ' + id);
  // Only mails the monitor could have listed may be changed.
  if (!message.isInInbox() || !isJobMail_(message.getSubject() || '', message.getPlainBody() || '')) {
    throw new Error('message not eligible: ' + id);
  }
  message.markRead();
  if (labelName) {
    const name = checkLabel_(labelName);
    const label = GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
    message.getThread().addLabel(label);
  }
}

function reply_(payload) {
  return ContentService.createTextOutput(JSON.stringify(payload)).setMimeType(
    ContentService.MimeType.JSON
  );
}
