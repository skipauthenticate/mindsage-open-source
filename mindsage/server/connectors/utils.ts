/**
 * Shared utilities for MindSage connectors.
 */

/**
 * Fetch with automatic retry and rate-limit handling.
 * Retries on 429 (rate limit) with Retry-After header support,
 * and on network errors with exponential backoff.
 */
export async function fetchWithRetry(
  url: string,
  options: RequestInit,
  retries = 3,
  baseDelayMs = 1000
): Promise<Response> {
  for (let i = 0; i < retries; i++) {
    try {
      const response = await fetch(url, options);
      if (response.status === 429) {
        const retryAfter = response.headers.get('retry-after');
        let waitTime = Math.pow(2, i) * baseDelayMs;
        if (retryAfter) {
          const parsed = parseInt(retryAfter, 10);
          if (!isNaN(parsed)) {
            waitTime = parsed * 1000;
          }
        }
        console.log(`[fetch] Rate limited, waiting ${waitTime}ms...`);
        await new Promise(resolve => setTimeout(resolve, waitTime));
        continue;
      }
      return response;
    } catch (error) {
      if (i === retries - 1) throw error;
      const waitTime = Math.pow(2, i) * baseDelayMs;
      await new Promise(resolve => setTimeout(resolve, waitTime));
    }
  }
  throw new Error('Max retries exceeded');
}
