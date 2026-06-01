import * as fs from 'fs';
import * as path from 'path';

// Configuration from environment
const EXPORTS_DIR = process.env.EXPORTS_DIR || './data/exports';
const ZIP_PATH = process.env.FACEBOOK_ZIP_PATH;

// Facebook uses Latin-1 encoding for Unicode characters in JSON
// This function fixes the mojibake issue
function fixFacebookEncoding(text: string): string {
  try {
    // Facebook encodes Unicode as escaped sequences in Latin-1
    // We need to decode them properly
    return text.replace(/\\u00([0-9a-fA-F]{2})/g, (_, hex) => {
      return String.fromCharCode(parseInt(hex, 16));
    });
  } catch {
    return text;
  }
}

// Deep fix encoding in an object
function fixEncodingDeep(obj: any): any {
  if (typeof obj === 'string') {
    return fixFacebookEncoding(obj);
  }
  if (Array.isArray(obj)) {
    return obj.map(fixEncodingDeep);
  }
  if (obj && typeof obj === 'object') {
    const fixed: any = {};
    for (const key of Object.keys(obj)) {
      fixed[key] = fixEncodingDeep(obj[key]);
    }
    return fixed;
  }
  return obj;
}

// Supported media extensions that we can't process yet
const PENDING_MEDIA_EXTENSIONS = new Set([
  '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic', '.heif',
  '.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v',
  '.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac',
]);

interface ExportedIds {
  posts: string[];
  comments: string[];
  messages: string[];
  other: string[];
  lastExport: string;
}

interface PendingMediaFile {
  originalPath: string;
  filename: string;
  type: 'photo' | 'video' | 'audio';
  extension: string;
  size: number;
  context?: {
    source: string;  // e.g., 'posts', 'messages', 'profile'
    timestamp?: number;
    description?: string;
    associatedWith?: string;  // e.g., post ID or message thread
  };
  storedAt: string;
  storedPath: string;
}

interface PendingMediaRegistry {
  files: PendingMediaFile[];
  lastUpdated: string;
  totalSize: number;
  counts: {
    photos: number;
    videos: number;
    audio: number;
  };
}

interface FacebookPost {
  timestamp: number;
  data?: Array<{
    post?: string;
    update_timestamp?: number;
  }>;
  attachments?: Array<{
    data?: Array<{
      media?: {
        uri?: string;
        description?: string;
        creation_timestamp?: number;
      };
      external_context?: {
        url?: string;
        name?: string;
      };
      text?: string;
    }>;
  }>;
  title?: string;
  tags?: Array<{ name: string }>;
}

interface FacebookComment {
  timestamp: number;
  data?: Array<{
    comment?: {
      timestamp?: number;
      comment?: string;
      author?: string;
    };
  }>;
  title?: string;
  attachments?: Array<any>;
}

interface FacebookMessage {
  sender_name: string;
  timestamp_ms: number;
  content?: string;
  type?: string;
  photos?: Array<{ uri: string; creation_timestamp: number }>;
  videos?: Array<{ uri: string; creation_timestamp: number }>;
  audio_files?: Array<{ uri: string; creation_timestamp: number }>;
  share?: { link?: string; share_text?: string };
  reactions?: Array<{ reaction: string; actor: string }>;
}

interface FacebookMessageThread {
  participants: Array<{ name: string }>;
  messages: FacebookMessage[];
  title: string;
  thread_path: string;
  is_still_participant: boolean;
}

function ensureDirectories(): void {
  if (!fs.existsSync(EXPORTS_DIR)) {
    fs.mkdirSync(EXPORTS_DIR, { recursive: true });
  }
  // Create pending media directory
  const pendingDir = path.join(EXPORTS_DIR, 'pending-media');
  if (!fs.existsSync(pendingDir)) {
    fs.mkdirSync(pendingDir, { recursive: true });
  }
}

function loadExportedIds(): ExportedIds {
  const exportedIdsFile = path.join(EXPORTS_DIR, '.exported-ids.json');
  if (fs.existsSync(exportedIdsFile)) {
    return JSON.parse(fs.readFileSync(exportedIdsFile, 'utf-8'));
  }
  return { posts: [], comments: [], messages: [], other: [], lastExport: '' };
}

function saveExportedIds(data: ExportedIds): void {
  const exportedIdsFile = path.join(EXPORTS_DIR, '.exported-ids.json');
  fs.writeFileSync(exportedIdsFile, JSON.stringify(data, null, 2));
}

function loadPendingMediaRegistry(): PendingMediaRegistry {
  const registryPath = path.join(EXPORTS_DIR, 'pending-media', '.registry.json');
  if (fs.existsSync(registryPath)) {
    return JSON.parse(fs.readFileSync(registryPath, 'utf-8'));
  }
  return {
    files: [],
    lastUpdated: '',
    totalSize: 0,
    counts: { photos: 0, videos: 0, audio: 0 },
  };
}

function savePendingMediaRegistry(registry: PendingMediaRegistry): void {
  const registryPath = path.join(EXPORTS_DIR, 'pending-media', '.registry.json');
  registry.lastUpdated = new Date().toISOString();
  fs.writeFileSync(registryPath, JSON.stringify(registry, null, 2));
}

function getMediaType(ext: string): 'photo' | 'video' | 'audio' {
  const photos = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic', '.heif'];
  const videos = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v'];
  if (photos.includes(ext)) return 'photo';
  if (videos.includes(ext)) return 'video';
  return 'audio';
}

async function processFacebookExport(zipPath: string): Promise<{
  postCount: number;
  commentCount: number;
  messageCount: number;
  mediaCount: number;
}> {
  const AdmZip = (await import('adm-zip')).default;
  const zip = new AdmZip(zipPath);
  const zipEntries = zip.getEntries();

  ensureDirectories();

  const exportedData = loadExportedIds();
  const exportedPosts = new Set(exportedData.posts);
  const exportedComments = new Set(exportedData.comments);
  const exportedMessages = new Set(exportedData.messages);
  const exportedOther = new Set(exportedData.other);

  const pendingRegistry = loadPendingMediaRegistry();

  let postCount = 0;
  let commentCount = 0;
  let messageCount = 0;
  let mediaCount = 0;

  console.log(`[processFacebookExport] Found ${zipEntries.length} entries in ZIP`);

  // First pass: collect all entries by type
  const postEntries: typeof zipEntries = [];
  const commentEntries: typeof zipEntries = [];
  const messageEntries: typeof zipEntries = [];
  const mediaEntries: typeof zipEntries = [];
  const otherJsonEntries: typeof zipEntries = [];

  for (const entry of zipEntries) {
    const entryName = entry.entryName.toLowerCase();
    const ext = path.extname(entryName).toLowerCase();

    if (entry.isDirectory) continue;

    // Categorize entries
    if (PENDING_MEDIA_EXTENSIONS.has(ext)) {
      mediaEntries.push(entry);
    } else if (entryName.includes('posts/') && entryName.endsWith('.json')) {
      postEntries.push(entry);
    } else if (entryName.includes('comments/') && entryName.endsWith('.json')) {
      commentEntries.push(entry);
    } else if (entryName.includes('messages/') && entryName.endsWith('.json')) {
      messageEntries.push(entry);
    } else if (entryName.endsWith('.json')) {
      otherJsonEntries.push(entry);
    }
  }

  console.log(`[processFacebookExport] Categories: ${postEntries.length} posts, ${commentEntries.length} comments, ${messageEntries.length} messages, ${mediaEntries.length} media, ${otherJsonEntries.length} other JSON`);

  // Process posts
  for (const entry of postEntries) {
    try {
      const content = entry.getData().toString('utf-8');
      const data = fixEncodingDeep(JSON.parse(content));

      if (Array.isArray(data)) {
        for (const post of data as FacebookPost[]) {
          const postId = `post_${post.timestamp}`;
          if (exportedPosts.has(postId)) continue;

          // Extract post text
          let postText = '';
          if (post.data) {
            postText = post.data.map(d => d.post || '').filter(Boolean).join('\n');
          }

          // Extract attachment context
          const attachments: string[] = [];
          if (post.attachments) {
            for (const att of post.attachments) {
              if (att.data) {
                for (const d of att.data) {
                  if (d.text) attachments.push(d.text);
                  if (d.external_context?.name) attachments.push(d.external_context.name);
                  if (d.media?.description) attachments.push(d.media.description);
                }
              }
            }
          }

          if (postText || attachments.length > 0) {
            const exportedPost = {
              type: 'post',
              id: postId,
              timestamp: post.timestamp,
              date: new Date(post.timestamp * 1000).toISOString(),
              title: post.title,
              content: postText,
              attachments: attachments.length > 0 ? attachments : undefined,
              tags: post.tags?.map(t => t.name),
              exportedAt: new Date().toISOString(),
            };

            const filename = `facebook_post_${post.timestamp}.json`;
            fs.writeFileSync(path.join(EXPORTS_DIR, filename), JSON.stringify(exportedPost, null, 2));
            exportedData.posts.push(postId);
            exportedPosts.add(postId);
            postCount++;
            console.log(`[processFacebookExport] ✓ Exported post from ${exportedPost.date}`);
          }
        }
      }
    } catch (error) {
      console.error(`[processFacebookExport] Error processing post entry ${entry.entryName}:`, error);
    }
  }

  // Process comments
  for (const entry of commentEntries) {
    try {
      const content = entry.getData().toString('utf-8');
      const data = fixEncodingDeep(JSON.parse(content));

      // Comments can be structured differently
      const comments = data.comments || (Array.isArray(data) ? data : [data]);

      for (const comment of comments) {
        const timestamp = comment.timestamp || comment.data?.[0]?.comment?.timestamp;
        if (!timestamp) continue;

        const commentId = `comment_${timestamp}`;
        if (exportedComments.has(commentId)) continue;

        let commentText = '';
        if (comment.data && Array.isArray(comment.data)) {
          commentText = comment.data
            .map((d: any) => d.comment?.comment || d.comment || '')
            .filter(Boolean)
            .join('\n');
        } else if (typeof comment.comment === 'string') {
          commentText = comment.comment;
        }

        if (commentText) {
          const exportedComment = {
            type: 'comment',
            id: commentId,
            timestamp,
            date: new Date(timestamp * 1000).toISOString(),
            title: comment.title,
            content: commentText,
            author: comment.data?.[0]?.comment?.author,
            exportedAt: new Date().toISOString(),
          };

          const filename = `facebook_comment_${timestamp}.json`;
          fs.writeFileSync(path.join(EXPORTS_DIR, filename), JSON.stringify(exportedComment, null, 2));
          exportedData.comments.push(commentId);
          exportedComments.add(commentId);
          commentCount++;
          console.log(`[processFacebookExport] ✓ Exported comment from ${exportedComment.date}`);
        }
      }
    } catch (error) {
      console.error(`[processFacebookExport] Error processing comment entry ${entry.entryName}:`, error);
    }
  }

  // Process messages
  for (const entry of messageEntries) {
    try {
      // Skip non-message JSON files in messages folder
      if (!entry.entryName.includes('message_') && !entry.entryName.endsWith('message_1.json')) {
        continue;
      }

      const content = entry.getData().toString('utf-8');
      const thread = fixEncodingDeep(JSON.parse(content)) as FacebookMessageThread;

      if (!thread.messages || !Array.isArray(thread.messages)) continue;

      const threadId = thread.thread_path || path.dirname(entry.entryName);
      const participants = thread.participants?.map(p => p.name).join(', ') || 'Unknown';

      // Export the entire thread as one document for context
      const threadMessages = thread.messages
        .filter(msg => msg.content || msg.share)
        .map(msg => ({
          sender: msg.sender_name,
          timestamp: msg.timestamp_ms,
          date: new Date(msg.timestamp_ms).toISOString(),
          content: msg.content || msg.share?.share_text || msg.share?.link || '',
          type: msg.type,
          hasMedia: !!(msg.photos?.length || msg.videos?.length || msg.audio_files?.length),
        }));

      if (threadMessages.length === 0) continue;

      const threadExportId = `thread_${Buffer.from(threadId).toString('base64').substring(0, 20)}`;
      if (exportedMessages.has(threadExportId)) continue;

      const exportedThread = {
        type: 'message_thread',
        id: threadExportId,
        threadPath: threadId,
        title: thread.title || `Chat with ${participants}`,
        participants,
        messageCount: threadMessages.length,
        messages: threadMessages,
        firstMessage: threadMessages[threadMessages.length - 1]?.date,
        lastMessage: threadMessages[0]?.date,
        exportedAt: new Date().toISOString(),
      };

      const safeThreadName = (thread.title || participants)
        .replace(/[^a-z0-9]/gi, '_')
        .substring(0, 40);
      const filename = `facebook_messages_${safeThreadName}_${Date.now()}.json`;
      fs.writeFileSync(path.join(EXPORTS_DIR, filename), JSON.stringify(exportedThread, null, 2));
      exportedData.messages.push(threadExportId);
      exportedMessages.add(threadExportId);
      messageCount += threadMessages.length;
      console.log(`[processFacebookExport] ✓ Exported ${threadMessages.length} messages from "${thread.title || participants}"`);

      // Track media files referenced in messages
      for (const msg of thread.messages) {
        const mediaRefs = [
          ...(msg.photos || []),
          ...(msg.videos || []),
          ...(msg.audio_files || []),
        ];
        for (const media of mediaRefs) {
          if (media.uri) {
            // Store reference for later - we'll extract the actual file below
            const ext = path.extname(media.uri).toLowerCase();
            if (PENDING_MEDIA_EXTENSIONS.has(ext)) {
              // This media is referenced but will be extracted in the media pass
            }
          }
        }
      }
    } catch (error) {
      console.error(`[processFacebookExport] Error processing message entry ${entry.entryName}:`, error);
    }
  }

  // Process other interesting JSON files
  const interestingFiles = [
    'your_search_history',
    'ads_interests',
    'friend_peer_group',
    'your_address_books',
    'profile_information',
    'pages_you_ve_liked',
    'posts_you_ve_liked',
    'your_saved_items',
    'your_places',
    'apps_and_websites',
  ];

  for (const entry of otherJsonEntries) {
    const baseName = path.basename(entry.entryName, '.json').toLowerCase();
    const isInteresting = interestingFiles.some(f => baseName.includes(f.replace(/_/g, '')));

    if (!isInteresting) continue;

    const otherId = `other_${baseName}`;
    if (exportedOther.has(otherId)) continue;

    try {
      const content = entry.getData().toString('utf-8');
      const data = fixEncodingDeep(JSON.parse(content));

      // Extract text content based on structure
      let textContent = '';
      if (typeof data === 'object') {
        textContent = JSON.stringify(data, null, 2);
      }

      if (textContent.length > 50) {  // Skip tiny files
        const exported = {
          type: 'facebook_data',
          category: baseName,
          id: otherId,
          data,
          exportedAt: new Date().toISOString(),
        };

        const filename = `facebook_data_${baseName}.json`;
        fs.writeFileSync(path.join(EXPORTS_DIR, filename), JSON.stringify(exported, null, 2));
        exportedData.other.push(otherId);
        exportedOther.add(otherId);
        console.log(`[processFacebookExport] ✓ Exported ${baseName}`);
      }
    } catch (error) {
      console.error(`[processFacebookExport] Error processing other entry ${entry.entryName}:`, error);
    }
  }

  // Process and store media files for future indexing
  console.log(`[processFacebookExport] Processing ${mediaEntries.length} media files for pending storage...`);
  const pendingMediaDir = path.join(EXPORTS_DIR, 'pending-media');

  for (const entry of mediaEntries) {
    try {
      const ext = path.extname(entry.entryName).toLowerCase();
      const mediaType = getMediaType(ext);
      const filename = path.basename(entry.entryName);

      // Determine context from path
      let source = 'unknown';
      if (entry.entryName.includes('messages/')) source = 'messages';
      else if (entry.entryName.includes('posts/')) source = 'posts';
      else if (entry.entryName.includes('photos_and_videos/')) source = 'photos_and_videos';
      else if (entry.entryName.includes('profile/')) source = 'profile';

      // Create a unique stored filename
      const storedFilename = `${Date.now()}_${filename}`;
      const storedPath = path.join(pendingMediaDir, storedFilename);

      // Extract and save the media file
      zip.extractEntryTo(entry, pendingMediaDir, false, true, false, storedFilename);

      // Get file size
      let size = 0;
      try {
        size = fs.statSync(storedPath).size;
      } catch {
        size = entry.header.size;
      }

      // Add to registry
      const pendingFile: PendingMediaFile = {
        originalPath: entry.entryName,
        filename: storedFilename,
        type: mediaType,
        extension: ext,
        size,
        context: {
          source,
        },
        storedAt: new Date().toISOString(),
        storedPath,
      };

      pendingRegistry.files.push(pendingFile);
      pendingRegistry.totalSize += size;
      pendingRegistry.counts[mediaType === 'photo' ? 'photos' : mediaType === 'video' ? 'videos' : 'audio']++;
      mediaCount++;
    } catch (error) {
      console.error(`[processFacebookExport] Error storing media ${entry.entryName}:`, error);
    }
  }

  // Save updated registries
  saveExportedIds(exportedData);
  savePendingMediaRegistry(pendingRegistry);

  return { postCount, commentCount, messageCount, mediaCount };
}

async function main(): Promise<void> {
  if (!ZIP_PATH) {
    console.error('Missing FACEBOOK_ZIP_PATH environment variable');
    console.error('Usage: FACEBOOK_ZIP_PATH=/path/to/facebook-export.zip npx tsx export-facebook.ts');
    process.exit(1);
  }

  if (!fs.existsSync(ZIP_PATH)) {
    console.error(`Facebook export file not found: ${ZIP_PATH}`);
    process.exit(1);
  }

  console.log('='.repeat(60));
  console.log('Starting Facebook Data Export Processor');
  console.log('='.repeat(60));
  console.log(`Processing: ${ZIP_PATH}`);

  try {
    const result = await processFacebookExport(ZIP_PATH);

    console.log('='.repeat(60));
    console.log('Export complete!');
    console.log(`Posts exported: ${result.postCount}`);
    console.log(`Comments exported: ${result.commentCount}`);
    console.log(`Messages exported: ${result.messageCount}`);
    console.log(`Media files stored for future indexing: ${result.mediaCount}`);
    console.log('='.repeat(60));

    if (result.mediaCount > 0) {
      console.log('');
      console.log('NOTE: Media files (photos, videos, audio) have been stored in');
      console.log(`      ${path.join(EXPORTS_DIR, 'pending-media')}`);
      console.log('      These will be indexed when image/video processing is supported.');
      console.log('');
    }
  } catch (error) {
    console.error('[main] Export failed:', error);
    throw error;
  }
}

// Export for use as module
export { processFacebookExport, PendingMediaRegistry, PendingMediaFile };

main().catch((error) => {
  console.error('Fatal error:', error);
  process.exit(1);
});
