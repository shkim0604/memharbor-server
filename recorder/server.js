const express = require('express');
const puppeteer = require('puppeteer');
const path = require('path');
const fs = require('fs');
const { v4: uuidv4 } = require('uuid');
const { exec } = require('child_process');
const { promisify } = require('util');
const admin = require('firebase-admin');

const execAsync = promisify(exec);

// Basic file logging (stdout + file)
const LOG_FILE = process.env.RECORDER_LOG_FILE || '/app/logs/recorder.log';
try {
  fs.mkdirSync(path.dirname(LOG_FILE), { recursive: true });
} catch (err) {
  // If log dir fails, fall back to stdout only.
  console.error('Failed to create log directory:', err.message);
}
const logStream = fs.createWriteStream(LOG_FILE, { flags: 'a' });
const formatEtTimestamp = (date) => {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
  const parts = Object.fromEntries(fmt.formatToParts(date).map(p => [p.type, p.value]));
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second} ET`;
};

const _log = (level, args) => {
  const ts = formatEtTimestamp(new Date());
  const line = `[${ts}] [${level}] ${args.join(' ')}\n`;
  try {
    logStream.write(line);
  } catch (_) {
    // ignore file write errors
  }
};
['log', 'info', 'warn', 'error'].forEach((level) => {
  const original = console[level].bind(console);
  console[level] = (...args) => {
    _log(level.toUpperCase(), args.map(a => (typeof a === 'string' ? a : JSON.stringify(a))));
    original(...args);
  };
});
process.on('uncaughtException', (err) => {
  console.error('uncaughtException:', err && err.stack ? err.stack : err);
});
process.on('unhandledRejection', (err) => {
  console.error('unhandledRejection:', err && err.stack ? err.stack : err);
});

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Serve Agora SDK locally to avoid CDN issues
const agoraSdkCandidates = [
  path.join(__dirname, 'node_modules', 'agora-rtc-sdk-ng'),
  path.join(__dirname, 'node_modules', 'agora-rtc-sdk-ng', 'dist'),
];
for (const sdkPath of agoraSdkCandidates) {
  if (fs.existsSync(sdkPath)) {
    app.use('/vendor', express.static(sdkPath));
  }
}

// Active recording sessions
const sessions = new Map();

// Recordings directory
const RECORDINGS_DIR = process.env.RECORDINGS_DIR || path.join(__dirname, 'recordings');
if (!fs.existsSync(RECORDINGS_DIR)) {
  fs.mkdirSync(RECORDINGS_DIR, { recursive: true });
}

// Config
const AGORA_APP_ID = process.env.AGORA_APP_ID || '';
const PORT = process.env.RECORDER_PORT || 3100;
const FIREBASE_STORAGE_BUCKET = process.env.FIREBASE_STORAGE_BUCKET || '';

// Initialize Firebase Admin
let firebaseInitialized = false;
const useEmulator = process.env.FIREBASE_USE_EMULATOR === 'true';

if (useEmulator) {
  // Emulator mode - no credentials needed
  process.env.FIRESTORE_EMULATOR_HOST = process.env.FIRESTORE_EMULATOR_HOST || 'localhost:8080';
  process.env.FIREBASE_STORAGE_EMULATOR_HOST = process.env.FIREBASE_STORAGE_EMULATOR_HOST || 'localhost:9199';
  
  try {
    admin.initializeApp({
      projectId: process.env.FIREBASE_PROJECT_ID || 'demo-project',
      storageBucket: FIREBASE_STORAGE_BUCKET || 'demo-project.appspot.com'
    });
    firebaseInitialized = true;
    console.log('Firebase Admin initialized with EMULATOR');
    console.log(`  Firestore: ${process.env.FIRESTORE_EMULATOR_HOST}`);
    console.log(`  Storage: ${process.env.FIREBASE_STORAGE_EMULATOR_HOST}`);
  } catch (error) {
    console.error('Firebase emulator initialization failed:', error.message);
  }
} else if (process.env.FIREBASE_SERVICE_ACCOUNT) {
  try {
    const serviceAccount = JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT);
    admin.initializeApp({
      credential: admin.credential.cert(serviceAccount),
      storageBucket: FIREBASE_STORAGE_BUCKET
    });
    firebaseInitialized = true;
    console.log('Firebase Admin initialized (production)');
  } catch (error) {
    console.error('Firebase initialization failed:', error.message);
  }
} else if (fs.existsSync(path.join(__dirname, 'firebase-service-account.json'))) {
  try {
    const serviceAccount = require('./firebase-service-account.json');
    admin.initializeApp({
      credential: admin.credential.cert(serviceAccount),
      storageBucket: FIREBASE_STORAGE_BUCKET
    });
    firebaseInitialized = true;
    console.log('Firebase Admin initialized from file');
  } catch (error) {
    console.error('Firebase initialization failed:', error.message);
  }
}

// Upload to Firebase Storage and save metadata to Firestore
async function uploadToFirebase(filepath, metadata) {
  if (!firebaseInitialized) {
    console.log('Firebase not initialized, skipping upload');
    return null;
  }

  try {
    const bucket = admin.storage().bucket();
    const filename = path.basename(filepath);
    const destination = `recordings/${filename}`;

    // Upload file
    await bucket.upload(filepath, {
      destination,
      metadata: {
        contentType: 'audio/wav',
        metadata: {
          channel: metadata.channel,
          groupId: metadata.groupId || '',
          user1: metadata.user1 || '',
          user2: metadata.user2 || '',
          duration: String(metadata.duration),
          recordedAt: metadata.recordedAt
        }
      }
    });

    // Get download URL (valid for long time)
    const file = bucket.file(destination);
    const [url] = await file.getSignedUrl({
      action: 'read',
      expires: '2099-12-31'
    });

    console.log(`Uploaded to Firebase: ${destination}`);

    // Save metadata to Firestore
    const db = admin.firestore();
    const docRef = await db.collection('recordings').add({
      filename,
      url,
      channel: metadata.channel,
      groupId: metadata.groupId || null,
      user1: metadata.user1 || null,
      user2: metadata.user2 || null,
      duration: metadata.duration,
      fileSize: metadata.fileSize,
      format: 'wav',
      spec: {
        sampleRate: 16000,
        channels: 1,
        bitDepth: 16
      },
      recordedAt: admin.firestore.Timestamp.fromDate(new Date(metadata.recordedAt)),
      createdAt: admin.firestore.FieldValue.serverTimestamp()
    });

    console.log(`Saved to Firestore: ${docRef.id}`);

    return {
      url,
      firestoreId: docRef.id,
      storagePath: destination
    };

  } catch (error) {
    console.error('Firebase upload failed:', error.message);
    return null;
  }
}

function buildRecordingFilename({ groupId, callerId, receiverId, fallbackChannel }) {
  const timestamp = formatEtTimestamp(new Date()).replace(/[: ]/g, '-');
  if (groupId && callerId && receiverId) {
    return `${groupId}_${callerId}_${receiverId}_${timestamp}.webm`;
  }
  return `${fallbackChannel}_${timestamp}.webm`;
}

// Convert WebM to WAV (AI-optimized: 16kHz, mono, 16-bit PCM)
async function convertToWav(webmPath, wavPath) {
  const command = `ffmpeg -i "${webmPath}" -acodec pcm_s16le -ar 16000 -ac 1 "${wavPath}" -y`;
  try {
    await execAsync(command);
    console.log(`Converted: ${path.basename(webmPath)} → ${path.basename(wavPath)}`);
    return true;
  } catch (error) {
    console.error(`FFmpeg conversion failed:`, error.message);
    return false;
  }
}

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', activeSessions: sessions.size });
});

// Start recording
app.post('/start', async (req, res) => {
  const { channel, token, uid, callerId, receiverId, groupId } = req.body;

  if (!channel) {
    return res.status(400).json({ error: 'missing_channel' });
  }

  if (!AGORA_APP_ID) {
    return res.status(500).json({ error: 'AGORA_APP_ID not configured' });
  }

  // Check if already recording this channel
  const existingSession = Array.from(sessions.values()).find(s => s.channel === channel);
  if (existingSession) {
    return res.status(409).json({ 
      error: 'already_recording', 
      sid: existingSession.sid,
      channel 
    });
  }

  const sid = uuidv4();
  const recordingUid = uid || Math.floor(Math.random() * 100000) + 900000;
  
  const filename = buildRecordingFilename({
    groupId,
    callerId,
    receiverId,
    fallbackChannel: channel,
  });
  const filepath = path.join(RECORDINGS_DIR, filename);

  try {
    console.log(`[${sid}] Starting recording for channel: ${channel}`);

    // Launch headless browser
    const browser = await puppeteer.launch({
      headless: 'new',
      executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
      args: [
        '--use-fake-ui-for-media-stream',
        '--use-fake-device-for-media-stream',
        '--allow-file-access',
        '--disable-web-security',
        '--autoplay-policy=no-user-gesture-required',
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
      ]
    });

    const page = await browser.newPage();

    // Enable console logging from page
    page.on('console', msg => {
      console.log(`[${sid}] Browser:`, msg.text());
    });

    // Load recorder page
    const recorderUrl = `http://localhost:${PORT}/recorder.html?appId=${AGORA_APP_ID}&channel=${encodeURIComponent(channel)}&token=${encodeURIComponent(token || '')}&uid=${recordingUid}&sid=${sid}`;
    await page.goto(recorderUrl);

    // Wait for connection
    await page.waitForFunction(() => window.recorderReady === true, { timeout: 30000 });

    // Store session
    sessions.set(sid, {
      sid,
      channel,
      uid: recordingUid,
      groupId: parsed.groupId,
      user1: parsed.user1,
      user2: parsed.user2,
      browser,
      page,
      filepath,
      filename,
      startedAt: new Date().toISOString(),
    });

    console.log(`[${sid}] Recording started successfully`);

    res.json({
      sid,
      channel,
      uid: recordingUid,
      filename,
      status: 'recording'
    });

  } catch (error) {
    console.error(`[${sid}] Failed to start recording:`, error);
    res.status(500).json({ error: 'recording_start_failed', message: error.message });
  }
});

// Stop recording
app.post('/stop', async (req, res) => {
  const { sid, channel } = req.body;

  let session;
  if (sid) {
    session = sessions.get(sid);
  } else if (channel) {
    session = Array.from(sessions.values()).find(s => s.channel === channel);
  }

  if (!session) {
    return res.status(404).json({ error: 'session_not_found' });
  }

  try {
    console.log(`[${session.sid}] Stopping recording...`);

    // Tell page to stop recording and get the blob
    const recordingData = await session.page.evaluate(() => {
      return window.stopRecording();
    });

    let wavFilename = null;
    let wavFilepath = null;

    if (recordingData) {
      // Save the WebM recording
      const buffer = Buffer.from(recordingData, 'base64');
      fs.writeFileSync(session.filepath, buffer);
      console.log(`[${session.sid}] Recording saved: ${session.filename}`);

      // Convert to WAV (AI-optimized format)
      wavFilename = session.filename.replace('.webm', '.wav');
      wavFilepath = session.filepath.replace('.webm', '.wav');
      
      const converted = await convertToWav(session.filepath, wavFilepath);
      if (converted) {
        // Remove original WebM to save space
        fs.unlinkSync(session.filepath);
        console.log(`[${session.sid}] Removed original WebM file`);
      } else {
        // Keep WebM if conversion failed
        wavFilename = null;
        wavFilepath = null;
      }
    }

    // Cleanup browser
    await session.browser.close();
    sessions.delete(session.sid);

    const duration = Date.now() - new Date(session.startedAt).getTime();
    const finalFilepath = wavFilepath || session.filepath;
    const finalFilename = wavFilename || session.filename;

    // Upload to Firebase
    let firebase = null;
    if (finalFilepath && fs.existsSync(finalFilepath)) {
      const stat = fs.statSync(finalFilepath);
      firebase = await uploadToFirebase(finalFilepath, {
        channel: session.channel,
        groupId: session.groupId,
        user1: session.user1,
        user2: session.user2,
        duration,
        fileSize: stat.size,
        recordedAt: session.startedAt
      });
    }

    res.json({
      sid: session.sid,
      channel: session.channel,
      groupId: session.groupId,
      user1: session.user1,
      user2: session.user2,
      filename: finalFilename,
      filepath: finalFilepath,
      format: wavFilename ? 'wav' : 'webm',
      spec: wavFilename ? {
        sampleRate: 16000,
        channels: 1,
        bitDepth: 16,
        codec: 'pcm_s16le'
      } : null,
      duration,
      firebase,
      status: 'stopped'
    });

  } catch (error) {
    console.error(`[${session.sid}] Failed to stop recording:`, error);
    
    // Force cleanup
    try {
      await session.browser.close();
    } catch (e) {}
    sessions.delete(session.sid);

    res.status(500).json({ error: 'recording_stop_failed', message: error.message });
  }
});

// List active sessions
app.get('/sessions', (req, res) => {
  const list = Array.from(sessions.values()).map(s => ({
    sid: s.sid,
    channel: s.channel,
    uid: s.uid,
    startedAt: s.startedAt,
  }));
  res.json({ sessions: list });
});

// List recordings
app.get('/recordings', (req, res) => {
  const files = fs.readdirSync(RECORDINGS_DIR)
    .filter(f => f.endsWith('.wav') || f.endsWith('.webm'))
    .map(f => {
      const stat = fs.statSync(path.join(RECORDINGS_DIR, f));
      const format = f.endsWith('.wav') ? 'wav' : 'webm';
      return {
        filename: f,
        format,
        size: stat.size,
        createdAt: stat.birthtime,
        // Estimate duration: WAV 16kHz mono 16bit = 32KB/s
        estimatedDuration: format === 'wav' ? Math.round(stat.size / 32000) : null,
      };
    })
    .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
  res.json({ recordings: files });
});

app.listen(PORT, () => {
  console.log(`Recording service running on http://localhost:${PORT}`);
  console.log(`Recordings directory: ${RECORDINGS_DIR}`);
});
