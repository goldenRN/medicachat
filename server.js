const http = require("node:http");
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");
const crypto = require("node:crypto");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { DatabaseSync } = require("node:sqlite");

const HOST = "127.0.0.1";
const PORT = 4173;
const ROOT_DIR = __dirname;
const DATA_DIR = path.join(ROOT_DIR, "data");
const UPLOAD_DIR = path.join(DATA_DIR, "uploads");
const DB_PATH = path.join(DATA_DIR, "app.db");
const USERS_PATH = path.join(DATA_DIR, "users.json");
const DOCS_PATH = path.join(DATA_DIR, "documents.json");
const HISTORIES_PATH = path.join(DATA_DIR, "histories.json");

const execFileAsync = promisify(execFile);

const MIME_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
};

const DEFAULT_PROMPTS = [
  "Triage-ийн улаан ангилалд ямар тохиолдол багтдаг вэ?",
  "Хэвтэн эмчлүүлэхийн өмнө ямар шалгалтууд хийх ёстой вэ?",
  "Халдвар хамгааллын үндсэн дүрмийг нэгтгээд өгөөч.",
  "Дүрс оношилгооны өмнөх бэлтгэлийг товч тайлбарла.",
];

const seedDocuments = [
  {
    id: crypto.randomUUID(),
    title: "Triage_Guide_2026.md",
    source: "System seed",
    summary: "Яаралтай тусламжийн шатлал, улаан/шар/ногоон ангиллын ерөнхий заавар.",
    content:
      "Улаан ангилалд амьсгалын дутагдал, зүрхний тогтворгүй байдал, шок орно. Шар ангилалд ойрын үнэлгээ шаардлагатай тогтвортой боловч эрсдэлтэй тохиолдлууд хамаарна. Ногоон ангилалд хүлээлгэж болох хөнгөн шинж тэмдэгтэй тохиолдол орно.",
    tags: ["triage", "emergency", "classification"],
    createdAt: new Date().toISOString(),
  },
  {
    id: crypto.randomUUID(),
    title: "Admission_Checklist.txt",
    source: "System seed",
    summary: "Хэвтэн эмчлүүлэхийн өмнөх бүртгэл, зөвшөөрөл, даатгалын шалгах хуудас.",
    content:
      "Хэвтэн эмчлүүлэхийн өмнө иргэний үнэмлэх, даатгалын мэдээлэл, эмийн харшлын асуумж, зөвшөөрлийн маягтыг баталгаажуулна. Өвчтөнд хоол, эмийн зааврыг урьдчилан тайлбарлана.",
    tags: ["admission", "checklist", "insurance"],
    createdAt: new Date().toISOString(),
  },
  {
    id: crypto.randomUUID(),
    title: "Infection_Control_Policy.json",
    source: "System seed",
    summary: "Гар ариутгал, хамгаалах хэрэгсэл, тусгаарлалтын дэглэмийн үндсэн бодлого.",
    content:
      "Өвчтөнтэй хүрэлцэхийн өмнө болон дараа гар ариутгана. Дуслын халдварын сэжигтэй үед маск, нүдний хамгаалалт хэрэглэнэ. Өндөр эрсдэлтэй орчинд нэг удаагийн бээлий, халат заавал хэрэглэнэ.",
    tags: ["infection", "ppe", "policy"],
    createdAt: new Date().toISOString(),
  },
  {
    id: crypto.randomUUID(),
    title: "Radiology_Preparation.csv",
    source: "System seed",
    summary: "Дүрс оношилгооны өмнөх бэлтгэл, өлөн ирэх эсэх, тодосгогч бодисын асуумж.",
    content:
      "Тодосгогч бодистой шинжилгээний өмнө бөөрний үзүүлэлт болон харшлын түүхийг асууна. Зарим шинжилгээнд 6-8 цаг өлөн байх шаардлагатай. Жирэмсний эрсдэлийг асуумжаар тодруулна.",
    tags: ["radiology", "contrast", "preparation"],
    createdAt: new Date().toISOString(),
  },
];

const seedUsers = [
  {
    id: crypto.randomUUID(),
    email: "admin@sosmedica.mn",
    password: "admin123",
    role: "admin",
    name: "System Admin",
  },
  {
    id: crypto.randomUUID(),
    email: "staff@sosmedica.mn",
    password: "staff123",
    role: "staff",
    name: "Clinical Staff",
  },
];

const sessions = new Map();
let db;

async function ensureBootstrap() {
  await fsp.mkdir(DATA_DIR, { recursive: true });
  await fsp.mkdir(UPLOAD_DIR, { recursive: true });
  initializeDatabase();
  await migrateLegacyJsonIfNeeded();
  seedDefaultsIfNeeded();
}

function initializeDatabase() {
  db = new DatabaseSync(DB_PATH);
  db.exec(`
    PRAGMA journal_mode = WAL;
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY,
      email TEXT NOT NULL UNIQUE,
      password TEXT NOT NULL,
      role TEXT NOT NULL,
      name TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS documents (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      source TEXT NOT NULL,
      summary TEXT NOT NULL,
      content TEXT NOT NULL,
      tags_json TEXT NOT NULL,
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS histories (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL,
      title TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS messages (
      id TEXT PRIMARY KEY,
      history_id TEXT NOT NULL,
      role TEXT NOT NULL,
      text TEXT NOT NULL,
      citations_json TEXT NOT NULL,
      timestamp TEXT NOT NULL,
      sort_order INTEGER NOT NULL,
      FOREIGN KEY (history_id) REFERENCES histories(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_histories_user_updated
      ON histories(user_id, updated_at DESC);

    CREATE INDEX IF NOT EXISTS idx_messages_history_sort
      ON messages(history_id, sort_order ASC);
  `);
}

async function migrateLegacyJsonIfNeeded() {
  if (countRows("users") !== 0 || countRows("documents") !== 0 || countRows("histories") !== 0) {
    return;
  }

  const legacyUsers = await readJson(USERS_PATH, []);
  const legacyDocuments = await readJson(DOCS_PATH, []);
  const legacyHistories = await readJson(HISTORIES_PATH, []);

  if (legacyUsers.length) {
    insertUsers(legacyUsers);
  }

  if (legacyDocuments.length) {
    insertDocuments(legacyDocuments);
  }

  if (legacyHistories.length) {
    insertHistories(legacyHistories);
  }
}

function seedDefaultsIfNeeded() {
  if (countRows("users") === 0) {
    insertUsers(seedUsers);
  }

  if (countRows("documents") === 0) {
    insertDocuments(seedDocuments);
  }
}

function createServer() {
  return http.createServer(async (req, res) => {
    try {
      const requestUrl = new URL(req.url, `http://${req.headers.host}`);
      const pathname = requestUrl.pathname;

      if (pathname.startsWith("/api/")) {
        await handleApi(req, res, requestUrl);
        return;
      }

      await serveStatic(res, pathname);
    } catch (error) {
      console.error(error);
      sendJson(res, 500, { error: error.message || "Internal server error" });
    }
  });
}

async function handleApi(req, res, requestUrl) {
  const { method } = req;
  const { pathname } = requestUrl;

  if (method === "POST" && pathname === "/api/login") {
    const body = await readJsonBody(req);
    const user = findUserByCredentials(body.email, body.password);

    if (!user) {
      sendJson(res, 401, { error: "И-мэйл эсвэл нууц үг буруу байна." });
      return;
    }

    const token = crypto.randomUUID();
    sessions.set(token, {
      userId: user.id,
      email: user.email,
      role: user.role,
      name: user.name,
    });

    sendJson(res, 200, {
      token,
      user: sanitizeUser(user),
    });
    return;
  }

  if (method === "POST" && pathname === "/api/logout") {
    const session = getSession(req);
    if (session) {
      sessions.delete(session.token);
    }
    sendJson(res, 200, { ok: true });
    return;
  }

  if (method === "GET" && pathname === "/api/bootstrap") {
    const session = requireSession(req, res);
    if (!session) {
      return;
    }

    sendJson(res, 200, {
      user: {
        email: session.email,
        role: session.role,
        name: session.name,
      },
      prompts: DEFAULT_PROMPTS,
      documents: listDocuments().map(sanitizeDocument),
      histories: listHistorySummariesByUser(session.userId),
    });
    return;
  }

  if (method === "GET" && pathname === "/api/history") {
    const session = requireSession(req, res);
    if (!session) {
      return;
    }

    const historyId = requestUrl.searchParams.get("id");
    const history = getHistoryById(historyId, session.userId);

    if (!history) {
      sendJson(res, 404, { error: "Chat history олдсонгүй." });
      return;
    }

    sendJson(res, 200, { history });
    return;
  }

  if (method === "POST" && pathname === "/api/history/new") {
    const session = requireSession(req, res);
    if (!session) {
      return;
    }

    const history = createHistoryRecord(session.userId, "Шинэ чат");
    sendJson(res, 201, { history: summarizeHistory(history) });
    return;
  }

  if (method === "POST" && pathname === "/api/upload") {
    const session = requireSession(req, res);
    if (!session) {
      return;
    }

    if (session.role !== "admin") {
      sendJson(res, 403, { error: "Файл нэмэх эрх зөвхөн admin хэрэглэгчид байна." });
      return;
    }

    const body = await readJsonBody(req);
    const files = Array.isArray(body.files) ? body.files : [];
    if (!files.length) {
      sendJson(res, 400, { error: "Upload хийх файл алга." });
      return;
    }

    const createdDocuments = [];
    for (const file of files) {
      const parsed = await parseUploadedFile(file, session.email);
      if (!parsed) {
        continue;
      }

      insertDocuments([parsed]);
      createdDocuments.push(parsed);
    }

    sendJson(res, 201, {
      documents: createdDocuments.map(sanitizeDocument),
    });
    return;
  }

  if (method === "POST" && pathname === "/api/chat") {
    const session = requireSession(req, res);
    if (!session) {
      return;
    }

    const body = await readJsonBody(req);
    const messageText = String(body.message || "").trim();
    const preferredHistoryId = String(body.historyId || "").trim();
    if (!messageText) {
      sendJson(res, 400, { error: "Асуулт хоосон байна." });
      return;
    }

    const documents = listDocuments();
    let history = preferredHistoryId ? getHistoryById(preferredHistoryId, session.userId) : null;
    if (!history) {
      history = createHistoryRecord(session.userId, buildHistoryTitle(messageText));
    }

    if (history.messages.length === 0) {
      updateHistoryTitle(history.id, buildHistoryTitle(messageText));
    }

    appendMessage(history.id, createMessage("user", messageText), history.messages.length);

    const rankedDocs = rankDocuments(messageText, documents);
    const replyText = buildAnswer(messageText, rankedDocs, documents, history.messages);
    const assistantMessage = createMessage("bot", replyText, rankedDocs.slice(0, 3).map(sanitizeDocument));
    appendMessage(history.id, assistantMessage, history.messages.length + 1);
    touchHistory(history.id);

    const refreshedHistory = getHistoryById(history.id, session.userId);
    sendJson(res, 200, {
      history: refreshedHistory,
      reply: assistantMessage,
      documents: documents.map(sanitizeDocument),
    });
    return;
  }

  sendJson(res, 404, { error: "Not found" });
}

async function serveStatic(res, pathname) {
  if (pathname === "/") {
    res.writeHead(302, { Location: "/login" });
    res.end();
    return;
  }

  const routeMap = {
    "/login": "/login.html",
    "/chat": "/chat.html",
  };
  const normalizedPath = routeMap[pathname] || pathname;
  const safePath = path.normalize(normalizedPath).replace(/^(\.\.[/\\])+/, "");
  const filePath = path.join(ROOT_DIR, safePath);

  if (!filePath.startsWith(ROOT_DIR)) {
    sendText(res, 403, "Forbidden");
    return;
  }

  try {
    const stat = await fsp.stat(filePath);
    if (stat.isDirectory()) {
      sendText(res, 403, "Forbidden");
      return;
    }

    const ext = path.extname(filePath);
    const contentType = MIME_TYPES[ext] || "application/octet-stream";
    const content = await fsp.readFile(filePath);
    res.writeHead(200, { "Content-Type": contentType });
    res.end(content);
  } catch {
    sendText(res, 404, "Not found");
  }
}

function getSession(req) {
  const rawHeader = req.headers.authorization || "";
  const token = rawHeader.startsWith("Bearer ") ? rawHeader.slice(7) : "";
  if (!token || !sessions.has(token)) {
    return null;
  }

  return {
    token,
    ...sessions.get(token),
  };
}

function requireSession(req, res) {
  const session = getSession(req);
  if (!session) {
    sendJson(res, 401, { error: "Session дууссан байна. Дахин нэвтэрнэ үү." });
    return null;
  }
  return session;
}

async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }

  const rawBody = Buffer.concat(chunks).toString("utf8");
  if (!rawBody) {
    return {};
  }

  try {
    return JSON.parse(rawBody);
  } catch {
    throw new Error("Invalid JSON body");
  }
}

async function readJson(filePath, fallback) {
  try {
    const raw = await fsp.readFile(filePath, "utf8");
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(payload));
}

function sendText(res, statusCode, text) {
  res.writeHead(statusCode, { "Content-Type": "text/plain; charset=utf-8" });
  res.end(text);
}

function countRows(tableName) {
  return db.prepare(`SELECT COUNT(*) AS count FROM ${tableName}`).get().count;
}

function insertUsers(users) {
  const statement = db.prepare(`
    INSERT OR IGNORE INTO users (id, email, password, role, name)
    VALUES (?, ?, ?, ?, ?)
  `);

  for (const user of users) {
    statement.run(
      user.id || crypto.randomUUID(),
      user.email,
      user.password,
      user.role,
      user.name,
    );
  }
}

function insertDocuments(documents) {
  const statement = db.prepare(`
    INSERT OR REPLACE INTO documents (id, title, source, summary, content, tags_json, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `);

  for (const document of documents) {
    statement.run(
      document.id || crypto.randomUUID(),
      document.title,
      document.source,
      document.summary,
      document.content,
      JSON.stringify(document.tags || []),
      document.createdAt || new Date().toISOString(),
    );
  }
}

function insertHistories(histories) {
  const insertHistoryStatement = db.prepare(`
    INSERT OR REPLACE INTO histories (id, user_id, title, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?)
  `);
  const insertMessageStatement = db.prepare(`
    INSERT OR REPLACE INTO messages (id, history_id, role, text, citations_json, timestamp, sort_order)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `);

  for (const history of histories) {
    insertHistoryStatement.run(
      history.id || crypto.randomUUID(),
      history.userId,
      history.title || "Шинэ чат",
      history.createdAt || new Date().toISOString(),
      history.updatedAt || new Date().toISOString(),
    );

    (history.messages || []).forEach((message, index) => {
      insertMessageStatement.run(
        message.id || crypto.randomUUID(),
        history.id,
        message.role,
        message.text,
        JSON.stringify(message.citations || []),
        message.timestamp || new Date().toISOString(),
        index,
      );
    });
  }
}

function findUserByCredentials(email, password) {
  const normalizedEmail = String(email || "").trim().toLowerCase();
  return db
    .prepare(`
      SELECT id, email, password, role, name
      FROM users
      WHERE lower(email) = ? AND password = ?
    `)
    .get(normalizedEmail, String(password || ""));
}

function listDocuments() {
  return db
    .prepare(`
      SELECT id, title, source, summary, content, tags_json, created_at
      FROM documents
      ORDER BY datetime(created_at) DESC, rowid DESC
    `)
    .all()
    .map(rowToDocument);
}

function listHistorySummariesByUser(userId) {
  return db
    .prepare(`
      SELECT id, title, created_at, updated_at
      FROM histories
      WHERE user_id = ?
      ORDER BY datetime(updated_at) DESC, rowid DESC
    `)
    .all(userId)
    .map((historyRow) => ({
      id: historyRow.id,
      title: historyRow.title,
      createdAt: historyRow.created_at,
      updatedAt: historyRow.updated_at,
      messageCount: db
        .prepare("SELECT COUNT(*) AS count FROM messages WHERE history_id = ?")
        .get(historyRow.id).count,
    }));
}

function getHistoryById(historyId, userId) {
  if (!historyId) {
    return null;
  }

  const historyRow = db
    .prepare(`
      SELECT id, user_id, title, created_at, updated_at
      FROM histories
      WHERE id = ? AND user_id = ?
    `)
    .get(historyId, userId);

  if (!historyRow) {
    return null;
  }

  const messages = db
    .prepare(`
      SELECT id, role, text, citations_json, timestamp, sort_order
      FROM messages
      WHERE history_id = ?
      ORDER BY sort_order ASC, rowid ASC
    `)
    .all(historyId)
    .map(rowToMessage);

  return {
    id: historyRow.id,
    userId: historyRow.user_id,
    title: historyRow.title,
    createdAt: historyRow.created_at,
    updatedAt: historyRow.updated_at,
    messageCount: messages.length,
    messages,
  };
}

function createHistoryRecord(userId, title) {
  const now = new Date().toISOString();
  const history = {
    id: crypto.randomUUID(),
    userId,
    title,
    createdAt: now,
    updatedAt: now,
    messages: [],
  };

  db.prepare(`
    INSERT INTO histories (id, user_id, title, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?)
  `).run(history.id, history.userId, history.title, history.createdAt, history.updatedAt);

  return history;
}

function updateHistoryTitle(historyId, title) {
  db.prepare(`
    UPDATE histories
    SET title = ?, updated_at = ?
    WHERE id = ?
  `).run(title, new Date().toISOString(), historyId);
}

function appendMessage(historyId, message, sortOrder) {
  db.prepare(`
    INSERT INTO messages (id, history_id, role, text, citations_json, timestamp, sort_order)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `).run(
    message.id,
    historyId,
    message.role,
    message.text,
    JSON.stringify(message.citations || []),
    message.timestamp,
    sortOrder,
  );
}

function touchHistory(historyId) {
  db.prepare(`
    UPDATE histories
    SET updated_at = ?
    WHERE id = ?
  `).run(new Date().toISOString(), historyId);
}

function rowToDocument(row) {
  return {
    id: row.id,
    title: row.title,
    source: row.source,
    summary: row.summary,
    content: row.content,
    tags: parseJson(row.tags_json, []),
    createdAt: row.created_at,
  };
}

function rowToMessage(row) {
  return {
    id: row.id,
    role: row.role,
    text: row.text,
    citations: parseJson(row.citations_json, []),
    timestamp: row.timestamp,
  };
}

function parseJson(value, fallback) {
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function sanitizeUser(user) {
  return {
    id: user.id,
    email: user.email,
    role: user.role,
    name: user.name,
  };
}

function sanitizeDocument(document) {
  return {
    id: document.id,
    title: document.title,
    source: document.source,
    summary: document.summary,
    tags: document.tags,
    createdAt: document.createdAt,
  };
}

function summarizeHistory(history) {
  return {
    id: history.id,
    title: history.title,
    createdAt: history.createdAt,
    updatedAt: history.updatedAt,
    messageCount: history.messages.length,
  };
}

function createMessage(role, text, citations = []) {
  return {
    id: crypto.randomUUID(),
    role,
    text,
    citations,
    timestamp: new Date().toISOString(),
  };
}

function buildHistoryTitle(text) {
  const compact = text.replace(/\s+/g, " ").trim();
  return compact.length > 42 ? `${compact.slice(0, 42)}...` : compact || "Шинэ чат";
}

function summarizeContent(text) {
  const compact = text.replace(/\s+/g, " ").trim();
  return compact ? `${compact.slice(0, 110)}${compact.length > 110 ? "..." : ""}` : "No preview available.";
}

function sanitizeFilename(name) {
  return String(name)
    .replace(/[^a-zа-яөүё0-9._ -]/gi, "_")
    .replace(/\s+/g, "-")
    .slice(0, 120);
}

async function parseUploadedFile(file, uploaderEmail) {
  const safeName = sanitizeFilename(file.name || "uploaded.txt");
  const extension = path.extname(safeName).toLowerCase();
  const timestamp = Date.now();
  const savedName = `${timestamp}-${safeName}`;
  const savedPath = path.join(UPLOAD_DIR, savedName);

  if (extension === ".pdf") {
    const base64 = String(file.content || "").trim();
    if (!base64) {
      return null;
    }

    const pdfBytes = Buffer.from(base64, "base64");
    await fsp.writeFile(savedPath, pdfBytes);
    const extractedText = (await extractPdfText(savedPath)).trim();
    if (!extractedText) {
      throw new Error(`"${safeName}" PDF-ээс текст уншиж чадсангүй.`);
    }

    return buildDocumentRecord(safeName, uploaderEmail, extractedText);
  }

  const content = String(file.content || "").trim();
  if (!content) {
    return null;
  }

  await fsp.writeFile(savedPath, content, "utf8");
  return buildDocumentRecord(safeName, uploaderEmail, content);
}

async function extractPdfText(pdfPath) {
  const { stdout } = await execFileAsync("pdftotext", ["-layout", pdfPath, "-"], {
    maxBuffer: 20 * 1024 * 1024,
  });
  return stdout;
}

function buildDocumentRecord(title, uploaderEmail, content) {
  return {
    id: crypto.randomUUID(),
    title,
    source: `Uploaded by ${uploaderEmail}`,
    summary: summarizeContent(content),
    content: content.slice(0, 12000),
    tags: deriveTags(content),
    createdAt: new Date().toISOString(),
  };
}

function deriveTags(text) {
  return tokenize(text).filter((token, index, arr) => arr.indexOf(token) === index).slice(0, 5);
}

function tokenize(text) {
  return String(text)
    .toLowerCase()
    .split(/[^a-zа-яөүё0-9]+/i)
    .filter((part) => part.length > 2);
}

function rankDocuments(question, documents) {
  const tokens = tokenize(`${question} ${normalizeQuestionForIntent(question)}`);

  const ranked = documents
    .map((document) => {
      const haystack = tokenize(
        `${document.title} ${document.summary} ${document.content} ${(document.tags || []).join(" ")}`,
      );
      let score = 0;

      tokens.forEach((token) => {
        if (haystack.includes(token)) {
          score += 3;
        }

        if (String(document.title).toLowerCase().includes(token)) {
          score += 2;
        }
      });

      return {
        ...document,
        score,
      };
    })
    .sort((left, right) => right.score - left.score);

  const top = ranked.filter((document) => document.score > 0);
  return top.length ? top : ranked.slice(0, 2);
}

function buildAnswer(question, rankedDocs, allDocuments = rankedDocs, historyMessages = []) {
  const listAnswer = buildListAnswer(question, rankedDocs, allDocuments, historyMessages);
  if (listAnswer) {
    return listAnswer;
  }

  const aggregateAnswer = buildAggregateAnswer(question, allDocuments, historyMessages);
  if (aggregateAnswer) {
    return aggregateAnswer;
  }

  const best = rankedDocs[0];
  const supporting = rankedDocs[1];
  const normalized = normalizeQuestionForIntent(question);

  if (normalized.includes("triage") || normalized.includes("улаан")) {
    return [
      "Triage баримтаас харахад улаан ангилалд амьсгалын дутагдал, зүрхний тогтворгүй байдал, шок зэрэг амь насанд аюултай шинжүүд орно.",
      "Ийм тохиолдолд өвчтөнийг нэн тэргүүнд үнэлж, яаралтай тусламжийн баг шууд оролцох ёстой.",
      supporting ? `Дэмжих холбоотой баримтад ${supporting.title} мөн урьдчилсан шалгах урсгалыг сануулж байна.` : "",
    ]
      .filter(Boolean)
      .join("\n\n");
  }

  if (normalized.includes("хэвтэн") || normalized.includes("admission")) {
    return [
      "Хэвтэн эмчлүүлэхийн өмнө бүртгэл, иргэний үнэмлэх, даатгалын мэдээлэл, эмийн харшлын асуумж, зөвшөөрлийн маягтыг баталгаажуулах хэрэгтэй.",
      "Мөн өвчтөнд хоол, эмийн урьдчилсан зааврыг тайлбарлаж өгөх нь чухал байна.",
      best ? `Энэ хариулт ${best.title}-д тулгуурлаж байна.` : "",
    ]
      .filter(Boolean)
      .join("\n\n");
  }

  if (normalized.includes("халдвар") || normalized.includes("infection") || normalized.includes("ppe")) {
    return [
      "Халдвар хамгааллын гол зарчим нь хүрэлцэхийн өмнө болон дараа гар ариутгах, эрсдэлтэй нөхцөлд зохих хамгаалах хэрэгсэл хэрэглэх явдал байна.",
      "Дуслын халдварын сэжигтэй үед маск, нүдний хамгаалалт, өндөр эрсдэлтэй үед нэг удаагийн бээлий ба халат нэмэлтээр хэрэглэнэ.",
      best ? `Илүү дэлгэрэнгүй ишлэл: ${best.content}` : "",
    ]
      .filter(Boolean)
      .join("\n\n");
  }

  if (normalized.includes("дүрс") || normalized.includes("radiology") || normalized.includes("өлөн")) {
    return [
      "Дүрс оношилгооны өмнө тодосгогч бодисын харшлын түүх, бөөрний үзүүлэлт, жирэмсний эрсдэлийг шалгах шаардлагатай.",
      "Зарим шинжилгээнд 6-8 цаг өлөн байх заавар ордог тул товлолт бүрт тусгайлан нягтална.",
      best ? `Энэ дүгнэлт ${best.title}-оос гарч байна.` : "",
    ]
      .filter(Boolean)
      .join("\n\n");
  }

  const snippets = rankedDocs
    .slice(0, 3)
    .map((document) => `- ${document.title}: ${document.summary}`)
    .join("\n");

  return [
    "Таны асуулттай хамгийн ойр баримтуудыг нэгтгэж хариуллаа.",
    snippets,
    "Хэрэв хүсвэл эдгээрээс аль нэг хүний дэлгэрэнгүй мэдээлэл эсвэл нэрсийн жагсаалтыг тусад нь гаргаж өгч болно.",
  ].join("\n\n");
}

function buildListAnswer(question, rankedDocs, allDocuments, historyMessages = []) {
  const normalized = normalizeQuestionForIntent(question);
  if (!isListQuestion(normalized)) {
    return null;
  }

  const requestedDate = resolveRequestedDate(normalized, historyMessages);
  let candidates = requestedDate
    ? allDocuments.filter((document) => documentMatchesDate(document, requestedDate))
    : allDocuments;

  if (normalized.includes("америк") || normalized.includes("american") || normalized.includes("usa")) {
    const usaCandidates = candidates.filter((document) => documentMatchesUsaIntent(document));
    if (!usaCandidates.length) {
      return "Америкийн визтэй холбоотой тохирох баримт олдсонгүй.";
    }
    candidates = usaCandidates;
  }

  if (!requestedDate) {
    const positiveRanked = rankedDocs.filter((document) => document.score > 0);
    if (positiveRanked.length) {
      candidates = positiveRanked;
    }
  }

  const namedPeople = candidates
    .filter((document) => isLikelyPersonDocument(document))
    .map((document) => ({
      name: extractPersonName(document),
      title: document.title,
    }))
    .filter((entry) => entry.name);

  const uniquePeople = dedupeByName(namedPeople);
  if (!uniquePeople.length) {
    return "Энэ асуултад тохирох нэрсийн жагсаалт олдсонгүй.";
  }

  const heading = requestedDate
    ? `${requestedDate.label}-нд бүртгэгдсэн нэрсийн жагсаалт`
    : "Олдсон нэрсийн жагсаалт";

  const showAll = normalized.includes("бүгд") || normalized.includes("bugd") || normalized.includes("all");
  const visiblePeople = showAll ? uniquePeople : uniquePeople.slice(0, 20);
  const lines = visiblePeople.map((entry, index) => `${index + 1}. ${entry.name}`);
  const remainder = !showAll && uniquePeople.length > 20
    ? `\n\nНийт ${uniquePeople.length} нэр олдлоо. Дээр эхний 20-г үзүүлэв.`
    : `\n\nНийт ${uniquePeople.length} нэр олдлоо.`;

  return `${heading}:\n\n${lines.join("\n")}${remainder}`;
}

function buildAggregateAnswer(question, documents, historyMessages = []) {
  const normalized = normalizeQuestionForIntent(question);
  if (!isCountQuestion(normalized)) {
    return null;
  }

  const requestedDate = resolveRequestedDate(normalized, historyMessages);
  if (!requestedDate) {
    return null;
  }

  const matchingDocuments = documents.filter((document) => documentMatchesDate(document, requestedDate));
  if (!matchingDocuments.length) {
    return `${requestedDate.label}-нд тохирох үзлэгийн баримт олдсонгүй.`;
  }

  const names = dedupeByName(
    matchingDocuments
      .map((document) => ({ name: extractPersonName(document) }))
      .filter((entry) => entry.name),
  )
    .slice(0, 10)
    .map((entry) => entry.name);

  return [
    `${requestedDate.label}-нд нийт ${matchingDocuments.length} хүний баримт байна.`,
    `Тооллыг тухайн өдрийн PDF баримтуудын тоогоор гаргалаа.`,
    names.length ? `Нэрсийн жишээ: ${names.join(", ")}` : "",
  ].join("\n\n");
}

function isCountQuestion(normalized) {
  return (
    normalized.includes("хэдэн") &&
    (normalized.includes("хүн") ||
      normalized.includes("өвчтөн") ||
      normalized.includes("үзүүлсэн") ||
      normalized.includes("ирсэн") ||
      normalized.includes("баримт"))
  );
}

function isListQuestion(normalized) {
  return (
    normalized.includes("жагсаалт") ||
    normalized.includes("нэрс") ||
    normalized.includes("хэн хэн") ||
    normalized.includes("хэн") ||
    normalized.includes("үйлчлүүлэгч") ||
    normalized.includes("bugd") ||
    normalized.includes("бүгд")
  );
}

function resolveRequestedDate(normalized, historyMessages = []) {
  const ownDate = extractQuestionDate(normalized);
  if (ownDate) {
    return ownDate;
  }

  const previousUserMessages = [...historyMessages]
    .filter((message) => message.role === "user")
    .reverse();

  for (const message of previousUserMessages) {
    const date = extractQuestionDate(normalizeQuestionForIntent(message.text));
    if (date) {
      return date;
    }
  }

  return null;
}

function extractQuestionDate(normalized) {
  const explicitYearMatch = normalized.match(/(20\d{2})[.\-/ ]*(\d{1,2})[.\-/ ]*(\d{1,2})/);
  if (explicitYearMatch) {
    const [, year, month, day] = explicitYearMatch;
    return buildDateDescriptor(Number(year), Number(month), Number(day));
  }

  const monthWordMatch = normalized.match(/(\d{1,2})\s*(?:сарын|сар(?:ын)?|sariin|sar(?:iin)?)\s*(\d{1,2})/i);
  if (monthWordMatch) {
    const [, month, day] = monthWordMatch;
    return buildDateDescriptor(null, Number(month), Number(day));
  }

  const monthDaySlashMatch = normalized.match(/(\d{1,2})\s*[\/.-]\s*(\d{1,2})/);
  if (monthDaySlashMatch) {
    const [, month, day] = monthDaySlashMatch;
    return buildDateDescriptor(null, Number(month), Number(day));
  }

  return null;
}

function buildDateDescriptor(year, month, day) {
  if (!month || !day) {
    return null;
  }

  const paddedMonth = String(month).padStart(2, "0");
  const paddedDay = String(day).padStart(2, "0");
  return {
    year,
    month,
    day,
    paddedMonth,
    paddedDay,
    label: `${month} сарын ${day}`,
  };
}

function normalizeQuestionForIntent(question) {
  let normalized = String(question || "").toLowerCase();
  const replacements = [
    [/\bners(?:iig|uud|ee|iin)?\b/g, " нэрс "],
    [/\bner(?:siin)?\b/g, " нэр "],
    [/\bbugdiig\b/g, " бүгдийг "],
    [/\bbugd(?:iig|iin|)\b/g, " бүгд "],
    [/\bharuulaad\b/g, " харуулаад "],
    [/\bharuul(?:ya|aad|ah)\b/g, " харуул "],
    [/\bog\b/g, " өг "],
    [/\bheden\b/g, " хэдэн "],
    [/\bhed\b/g, " хэд "],
    [/\bhun\b/g, " хүн "],
    [/\buvchtun\b/g, " өвчтөн "],
    [/\bovchtun\b/g, " өвчтөн "],
    [/\buzuulsen\b/g, " үзүүлсэн "],
    [/\buzeulsen\b/g, " үзүүлсэн "],
    [/\buzuuleh\b/g, " үзүүлэх "],
    [/\bhenhen\b/g, " хэн хэн "],
    [/\bhen\b/g, " хэн "],
    [/\bjagsaalt\b/g, " жагсаалт "],
    [/\builchluulegch(?:diin|id|)\b/g, " үйлчлүүлэгч "],
    [/\bviziin\b/g, " визийн "],
    [/\bamerikiin\b/g, " америкийн "],
    [/\bamerika?n?\b/g, " америк "],
    [/\busa\b/g, " usa "],
    [/\bsariin\b/g, " сарын "],
    [/\bsar(?:iin)?\b/g, " сар "],
    [/\bnd\b/g, " нд "],
  ];

  for (const [pattern, replacement] of replacements) {
    normalized = normalized.replace(pattern, replacement);
  }

  return normalized.replace(/\s+/g, " ").trim();
}

function documentMatchesDate(document, dateDescriptor) {
  const haystack = `${document.title}\n${document.summary}\n${document.content}`.toLowerCase();
  const mmSlashDd = `${dateDescriptor.month}/${dateDescriptor.day}`;
  const mmSlashDdYear = dateDescriptor.year
    ? `${dateDescriptor.month}/${dateDescriptor.day}/${dateDescriptor.year}`
    : null;
  const yyyyMmDdCompact = dateDescriptor.year
    ? `${dateDescriptor.year}${dateDescriptor.paddedMonth}${dateDescriptor.paddedDay}`
    : null;
  const yyyyDotMmDotDd = dateDescriptor.year
    ? `${dateDescriptor.year}.${dateDescriptor.paddedMonth}.${dateDescriptor.paddedDay}`
    : null;
  const dashPattern = `-${dateDescriptor.month}-${dateDescriptor.day}`;
  const compactDashPattern = `-${dateDescriptor.paddedMonth}-${dateDescriptor.paddedDay}`;

  if (haystack.includes(dashPattern) || haystack.includes(compactDashPattern) || haystack.includes(mmSlashDd)) {
    return true;
  }

  if (mmSlashDdYear && haystack.includes(mmSlashDdYear)) {
    return true;
  }

  if (yyyyMmDdCompact && haystack.includes(yyyyMmDdCompact)) {
    return true;
  }

  if (yyyyDotMmDotDd && haystack.includes(yyyyDotMmDotDd)) {
    return true;
  }

  return false;
}

function documentMatchesUsaIntent(document) {
  const haystack = `${document.title}\n${document.summary}\n${document.content}`.toLowerCase();
  return (
    haystack.includes("usa") ||
    haystack.includes("u.s.") ||
    haystack.includes("united states") ||
    haystack.includes("америк")
  );
}

function extractPersonName(document) {
  const text = `${document.content}\n${document.summary}`;

  const mongolianNameMatch = text.match(/Нэр:\s*([^\n\r]+?)(?:\s+Хүйс:|\s+Регистр|\s+ШИНЖИЛГЭЭНИЙ|\s*$)/i);
  const mongolianParentMatch = text.match(/Эцэг\/эхийн нэр:\s*([^\n\r]+?)(?:\s+Нас:|\s*$)/i);
  if (mongolianNameMatch) {
    const primaryName = normalizeWhitespace(mongolianNameMatch[1]);
    const parentName = mongolianParentMatch ? normalizeWhitespace(mongolianParentMatch[1]) : "";
    return parentName ? `${primaryName} (${parentName})` : primaryName;
  }

  const englishNameMatch = text.match(/Name:\s*([A-Z][A-Z' -]+,\s*[A-Z][A-Z' -]+)/);
  if (englishNameMatch) {
    return normalizeWhitespace(englishNameMatch[1]);
  }

  return extractNameFromTitle(document.title);
}

function extractNameFromTitle(title) {
  const withoutExtension = title.replace(/\.pdf$/i, "");
  const withoutDate = withoutExtension.replace(/[-_ ]?(20\d{6}|\d{1,2}-\d{1,2})$/i, "");
  return normalizeWhitespace(withoutDate.replace(/[-_]+/g, " "));
}

function isLikelyPersonDocument(document) {
  const title = String(document.title || "").toLowerCase();
  const content = String(document.content || "");

  if (title.endsWith(".pdf")) {
    return true;
  }

  return /Нэр:\s*|Name:\s*/i.test(content);
}

function normalizeWhitespace(value) {
  return String(value).replace(/\s+/g, " ").trim();
}

function dedupeByName(entries) {
  const seen = new Set();
  const unique = [];

  for (const entry of entries) {
    const key = entry.name.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    unique.push(entry);
  }

  return unique;
}

async function main() {
  await ensureBootstrap();
  const server = createServer();
  server.listen(PORT, HOST, () => {
    console.log(`Server listening on http://${HOST}:${PORT}`);
    console.log(`SQLite DB: ${DB_PATH}`);
  });
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
