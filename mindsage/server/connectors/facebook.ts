/**
 * Facebook Data Export Processor for MindSage
 *
 * Processes ZIP exports from Facebook's "Download Your Information" feature.
 * Extracted from server/index.ts for maintainability.
 *
 * Supported data types:
 *   - Posts (posts/your_posts_1.json)
 *   - Comments (comments/comments.json)
 *   - Messages (messages/inbox/{person}/message_*.json)
 *   - Profile data, search history, ad interests, liked pages
 *   - Media files (stored for future processing)
 */

import * as fs from 'fs';
import * as path from 'path';

// --- Types ---

export interface PendingMediaFile {
  originalPath: string;
  filename: string;
  type: 'photo' | 'video' | 'audio';
  extension: string;
  size: number;
  context?: {
    source: string;
    timestamp?: number;
    description?: string;
  };
  storedAt: string;
  storedPath: string;
}

export interface PendingMediaRegistry {
  files: PendingMediaFile[];
  lastUpdated: string;
  totalSize: number;
  counts: { photos: number; videos: number; audio: number };
}

export interface FacebookExportResult {
  postCount: number;
  commentCount: number;
  messageCount: number;
  mediaCount: number;
}

// --- Constants ---

const PHOTO_EXTENSIONS = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic', '.heif']);
const VIDEO_EXTENSIONS = new Set(['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v']);
const AUDIO_EXTENSIONS = new Set(['.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac']);
const PENDING_MEDIA_EXTENSIONS = new Set([...PHOTO_EXTENSIONS, ...VIDEO_EXTENSIONS, ...AUDIO_EXTENSIONS]);

// --- Helpers ---

function getMediaType(ext: string): 'photo' | 'video' | 'audio' {
  if (PHOTO_EXTENSIONS.has(ext)) return 'photo';
  if (VIDEO_EXTENSIONS.has(ext)) return 'video';
  return 'audio';
}

function fixFacebookEncoding(text: string): string {
  try {
    return text.replace(/\\u00([0-9a-fA-F]{2})/g, (_, hex) => {
      return String.fromCharCode(parseInt(hex, 16));
    });
  } catch {
    return text;
  }
}

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

// --- Main Processor ---

/**
 * Process a Facebook data export ZIP file.
 * Extracts text content to JSON files and stores media for future indexing.
 */
export async function processFacebookExport(
  connectorId: string,
  zipPath: string,
  exportsDir: string
): Promise<FacebookExportResult> {
  const AdmZip = (await import('adm-zip')).default;
  const zip = new AdmZip(zipPath);
  const zipEntries = zip.getEntries();

  const exportDir = path.join(exportsDir, connectorId);
  if (!fs.existsSync(exportDir)) {
    fs.mkdirSync(exportDir, { recursive: true });
  }

  const pendingMediaDir = path.join(exportDir, 'pending-media');
  if (!fs.existsSync(pendingMediaDir)) {
    fs.mkdirSync(pendingMediaDir, { recursive: true });
  }

  let postCount = 0;
  let commentCount = 0;
  let messageCount = 0;
  let mediaCount = 0;
  let fileCounter = 0; // Avoids filename collisions for same-timestamp items

  // Load pending media registry
  const registryPath = path.join(pendingMediaDir, '.registry.json');
  let pendingRegistry: PendingMediaRegistry = {
    files: [],
    lastUpdated: '',
    totalSize: 0,
    counts: { photos: 0, videos: 0, audio: 0 },
  };
  if (fs.existsSync(registryPath)) {
    try {
      pendingRegistry = JSON.parse(fs.readFileSync(registryPath, 'utf-8'));
    } catch (error) {
      console.error('[facebook] Error reading media registry, starting fresh:', error);
    }
  }

  console.log(`[facebook] Found ${zipEntries.length} entries in ZIP`);

  for (const entry of zipEntries) {
    if (entry.isDirectory) continue;

    const entryName = entry.entryName.toLowerCase();
    const ext = path.extname(entryName).toLowerCase();

    // Handle media files - store for future indexing
    if (PENDING_MEDIA_EXTENSIONS.has(ext)) {
      try {
        const mediaType = getMediaType(ext);
        const filename = `${Date.now()}_${path.basename(entry.entryName)}`;
        const storedPath = path.join(pendingMediaDir, filename);

        fs.writeFileSync(storedPath, entry.getData());

        let source = 'unknown';
        if (entryName.includes('messages/')) source = 'messages';
        else if (entryName.includes('posts/')) source = 'posts';
        else if (entryName.includes('photos_and_videos/')) source = 'photos_and_videos';
        else if (entryName.includes('profile/')) source = 'profile';

        const size = entry.header.size;
        pendingRegistry.files.push({
          originalPath: entry.entryName,
          filename,
          type: mediaType,
          extension: ext,
          size,
          context: { source },
          storedAt: new Date().toISOString(),
          storedPath,
        });
        pendingRegistry.totalSize += size;
        pendingRegistry.counts[mediaType === 'photo' ? 'photos' : mediaType === 'video' ? 'videos' : 'audio']++;
        mediaCount++;
      } catch (error) {
        console.error(`[facebook] Error storing media ${entry.entryName}:`, error);
      }
      continue;
    }

    if (!entryName.endsWith('.json')) continue;

    try {
      const content = entry.getData().toString('utf-8');
      const data = fixEncodingDeep(JSON.parse(content));

      // Process posts
      if (entryName.includes('posts/') && Array.isArray(data)) {
        for (const post of data) {
          if (!post.timestamp) continue;

          let postText = '';
          if (post.data && Array.isArray(post.data)) {
            postText = post.data.map((d: any) => d.post || '').filter(Boolean).join('\n');
          }

          const attachmentTexts: string[] = [];
          if (post.attachments) {
            for (const att of post.attachments) {
              if (att.data && Array.isArray(att.data)) {
                for (const d of att.data) {
                  if (d.text) attachmentTexts.push(d.text);
                  if (d.external_context?.name) attachmentTexts.push(d.external_context.name);
                  if (d.media?.description) attachmentTexts.push(d.media.description);
                }
              }
            }
          }

          if (postText || attachmentTexts.length > 0) {
            const exportedPost = {
              type: 'post',
              timestamp: post.timestamp,
              date: new Date(post.timestamp * 1000).toISOString(),
              title: post.title,
              content: postText,
              attachments: attachmentTexts.length > 0 ? attachmentTexts : undefined,
              tags: post.tags?.map((t: any) => t.name),
              exportedAt: new Date().toISOString(),
            };

            const filename = `facebook_post_${post.timestamp}_${fileCounter++}.json`;
            fs.writeFileSync(path.join(exportDir, filename), JSON.stringify(exportedPost, null, 2));
            postCount++;
          }
        }
      }

      // Process comments
      else if (entryName.includes('comments/')) {
        const comments = data.comments || (Array.isArray(data) ? data : []);
        for (const comment of comments) {
          const timestamp = comment.timestamp || comment.data?.[0]?.comment?.timestamp;
          if (!timestamp) continue;

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
              timestamp,
              date: new Date(timestamp * 1000).toISOString(),
              title: comment.title,
              content: commentText,
              exportedAt: new Date().toISOString(),
            };

            const filename = `facebook_comment_${timestamp}_${fileCounter++}.json`;
            fs.writeFileSync(path.join(exportDir, filename), JSON.stringify(exportedComment, null, 2));
            commentCount++;
          }
        }
      }

      // Process messages
      else if (entryName.includes('messages/') && (entryName.includes('message_') || entryName.endsWith('message_1.json'))) {
        if (!data.messages || !Array.isArray(data.messages)) continue;

        const participants = data.participants?.map((p: any) => p.name).join(', ') || 'Unknown';
        const threadMessages = data.messages
          .filter((msg: any) => msg.content || msg.share)
          .map((msg: any) => ({
            sender: msg.sender_name,
            timestamp: msg.timestamp_ms,
            date: new Date(msg.timestamp_ms).toISOString(),
            content: msg.content || msg.share?.share_text || msg.share?.link || '',
            type: msg.type,
            hasMedia: !!(msg.photos?.length || msg.videos?.length || msg.audio_files?.length),
          }));

        if (threadMessages.length > 0) {
          const exportedThread = {
            type: 'message_thread',
            title: data.title || `Chat with ${participants}`,
            participants,
            messageCount: threadMessages.length,
            messages: threadMessages,
            firstMessage: threadMessages[threadMessages.length - 1]?.date,
            lastMessage: threadMessages[0]?.date,
            exportedAt: new Date().toISOString(),
          };

          const safeThreadName = (data.title || participants)
            .replace(/[^a-z0-9]/gi, '_')
            .substring(0, 40);
          const filename = `facebook_messages_${safeThreadName}_${Date.now()}.json`;
          fs.writeFileSync(path.join(exportDir, filename), JSON.stringify(exportedThread, null, 2));
          messageCount += threadMessages.length;
        }
      }

      // Process other interesting data
      else {
        const baseName = path.basename(entry.entryName, '.json').toLowerCase();
        const interestingPatterns = [
          'search_history', 'ads_interests', 'profile_information',
          'pages_you', 'posts_you', 'saved_items', 'your_places',
        ];

        if (interestingPatterns.some(p => baseName.includes(p))) {
          const exported = {
            type: 'facebook_data',
            category: baseName,
            data,
            exportedAt: new Date().toISOString(),
          };

          const filename = `facebook_data_${baseName}.json`;
          fs.writeFileSync(path.join(exportDir, filename), JSON.stringify(exported, null, 2));
        }
      }
    } catch (error) {
      console.error(`[facebook] Error processing ${entry.entryName}:`, error);
    }
  }

  // Save pending media registry
  pendingRegistry.lastUpdated = new Date().toISOString();
  fs.writeFileSync(registryPath, JSON.stringify(pendingRegistry, null, 2));

  console.log(`[facebook] Complete: ${postCount} posts, ${commentCount} comments, ${messageCount} messages, ${mediaCount} media stored`);
  return { postCount, commentCount, messageCount, mediaCount };
}

/**
 * Load pending media registry for a connector.
 */
export function loadPendingMediaRegistry(
  connectorId: string,
  exportsDir: string
): PendingMediaRegistry | null {
  const registryPath = path.join(exportsDir, connectorId, 'pending-media', '.registry.json');
  try {
    if (fs.existsSync(registryPath)) {
      return JSON.parse(fs.readFileSync(registryPath, 'utf-8')) as PendingMediaRegistry;
    }
  } catch (error) {
    console.error(`[facebook] Error reading media registry for ${connectorId}:`, error);
  }
  return null;
}
