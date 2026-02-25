const ALLOWED_HOSTS = new Set([
  'facebook.com', 'www.facebook.com', 'm.facebook.com', 'web.facebook.com',
  'fb.com', 'www.fb.com', 'fb.watch', 'www.fb.watch',
]);

function isFacebookUrl(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return ALLOWED_HOSTS.has(host) || host.endsWith('.facebook.com');
  } catch {
    return false;
  }
}

function extractFbidFromUrl(url) {
  try {
    const parsed = new URL(url);
    // /photo/?fbid=123 or /photo.php?fbid=123
    const fbid = parsed.searchParams.get('fbid');
    if (fbid && /^\d+$/.test(fbid)) return fbid;
    // /photo/123 (path-based)
    const m = parsed.pathname.match(/\/photo\/(\d+)/);
    if (m) return m[1];
  } catch {}
  return null;
}

function buildLookasideUrl(fbid) {
  return `https://lookaside.fbsbx.com/lookaside/crawler/media/?media_id=${fbid}`;
}

async function fetchLookasideImage(fbid, debug, debugLog) {
  const url = buildLookasideUrl(fbid);
  try {
    const resp = await fetch(url, {
      headers: { 'User-Agent': 'Twitterbot/1.0' },
      redirect: 'follow',
    });
    const contentType = resp.headers.get('Content-Type') || '';
    const isImage = contentType.startsWith('image/');

    if (debug) {
      debugLog.push({
        step: 'lookaside',
        url,
        status: resp.status,
        contentType,
        isImage,
      });
    }

    if (resp.ok && isImage) {
      return { success: true, url, contentType };
    }
  } catch (err) {
    if (debug) {
      debugLog.push({ step: 'lookaside', url, error: err.message });
    }
  }
  return { success: false };
}

function decodeEntities(str) {
  return str
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(parseInt(dec, 10)))
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'");
}

function extractOgTag(html, property) {
  // Match both property="og:..." and name="og:..." variants
  const patterns = [
    new RegExp(`<meta[^>]+property=["']${property}["'][^>]+content=["']([^"']*?)["']`, 'i'),
    new RegExp(`<meta[^>]+content=["']([^"']*?)["'][^>]+property=["']${property}["']`, 'i'),
  ];
  for (const re of patterns) {
    const m = html.match(re);
    if (m && m[1]) return decodeEntities(m[1].trim());
  }
  return '';
}

function extractStoryUrlFromHtml(html) {
  // Facebook login pages embed the real post URL in meta refresh or noscript redirects
  // e.g. <meta http-equiv="refresh" content="0; URL=/login/?next=https%3A%2F%2F...story.php%3Fstory_fbid%3DXXX%26id%3DYYY">
  // Extract any story.php or permalink.php URL from the HTML
  const patterns = [
    /story\.php\?story_fbid=(\d+)&(?:amp;)?id=(\d+)/,
    /story_fbid%3D(\d+)%26(?:amp;)?id%3D(\d+)/,
    /story_fbid%253D(\d+)%2526id%253D(\d+)/,
  ];
  for (const re of patterns) {
    const m = html.match(re);
    if (m && m[1] && m[2]) {
      return { storyFbid: m[1], id: m[2] };
    }
  }
  return null;
}

const GENERIC_FB_TITLES = new Set([
  'facebook', 'facebook - log in or sign up', 'log in to facebook',
  'facebook – log in or sign up', 'log in or sign up to view',
]);

function isGenericFacebookMetadata(title, description) {
  if (!title) return true;
  const t = title.trim().toLowerCase();
  if (GENERIC_FB_TITLES.has(t)) return true;
  if (t.startsWith('log in') || t.startsWith('sign up')) return true;
  const d = (description || '').trim().toLowerCase();
  const genericDescs = [
    'connect with friends, family and other people you know',
    'create an account or log into facebook',
    'log into facebook to start sharing',
    'see posts, photos and more on facebook',
  ];
  return genericDescs.some(gd => d.startsWith(gd));
}

function toMobileUrl(url) {
  // Convert www.facebook.com URL to m.facebook.com
  // m.facebook.com serves lightweight HTML with OG tags even for posts
  // that www.facebook.com renders only via JavaScript
  try {
    const parsed = new URL(url);
    if (['www.facebook.com', 'facebook.com', 'web.facebook.com'].includes(parsed.hostname.toLowerCase())) {
      parsed.hostname = 'm.facebook.com';
      return parsed.href;
    }
  } catch {}
  return url;
}

async function fetchAndExtract(url, debug, debugLog, stepLabel) {
  const resp = await fetch(url, {
    headers: { 'User-Agent': 'Twitterbot/1.0' },
    redirect: 'follow',
  });

  if (!resp.ok) {
    return { error: `Facebook returned HTTP ${resp.status}` };
  }

  const html = await resp.text();
  const title = extractOgTag(html, 'og:title');
  const description = extractOgTag(html, 'og:description');
  const image = extractOgTag(html, 'og:image');

  if (debug) {
    const metaTags = [...html.matchAll(/<meta[^>]+>/gi)].map(m => m[0]).slice(0, 30);
    debugLog.push({
      step: stepLabel,
      url,
      finalUrl: resp.url,
      status: resp.status,
      htmlLength: html.length,
      title,
      description,
      image,
      metaTags,
    });
  }

  // Filter out generic Facebook login/boilerplate metadata
  const isGeneric = isGenericFacebookMetadata(title, description);

  return {
    title: isGeneric ? '' : title,
    description: isGeneric ? '' : description,
    image: isGeneric ? '' : image,
    finalUrl: resp.url || url,
    html,
  };
}

async function fetchFacebookPage(url, debug = false) {
  const debugLog = [];

  // Step 1: Fetch the original URL
  const firstResult = await fetchAndExtract(url, debug, debugLog, 'www');
  if (firstResult.error) {
    return { error: firstResult.error, finalUrl: url, debugLog };
  }
  if (firstResult.title || firstResult.description) {
    return { title: firstResult.title, description: firstResult.description, image: firstResult.image, finalUrl: firstResult.finalUrl, debugLog };
  }

  // Step 2: For /share/ URLs, try to extract the canonical post URL from the
  // login page HTML (story_fbid + id), then convert to /{id}/posts/{fbid} format
  const isShareUrl = /facebook\.com\/share\//i.test(url);
  if (isShareUrl && firstResult.html) {
    const storyInfo = extractStoryUrlFromHtml(firstResult.html);
    if (storyInfo) {
      const postUrl = `https://www.facebook.com/${storyInfo.id}/posts/${storyInfo.storyFbid}`;
      if (debug) debugLog.push({ info: `Resolved share → ${postUrl}` });
      const postResult = await fetchAndExtract(postUrl, debug, debugLog, 'resolved-post');
      if (!postResult.error && (postResult.title || postResult.description)) {
        return { title: postResult.title, description: postResult.description, image: postResult.image, finalUrl: postResult.finalUrl, debugLog };
      }
    } else if (debug) {
      debugLog.push({ info: 'No story_fbid found in HTML' });
    }
  }

  // Step 3: Try m.facebook.com
  const mobileUrl = toMobileUrl(url);
  if (mobileUrl !== url) {
    if (debug) debugLog.push({ info: `Trying mobile: ${mobileUrl}` });
    const mResult = await fetchAndExtract(mobileUrl, debug, debugLog, 'mobile');
    if (!mResult.error && (mResult.title || mResult.description)) {
      return { title: mResult.title, description: mResult.description, image: mResult.image, finalUrl: mResult.finalUrl, debugLog };
    }
  }

  // Step 4: For /photo/ URLs, try lookaside crawler media endpoint
  const fbid = extractFbidFromUrl(url);
  if (fbid) {
    if (debug) debugLog.push({ info: `Photo URL detected, fbid=${fbid}, trying lookaside` });
    const lookResult = await fetchLookasideImage(fbid, debug, debugLog);
    if (lookResult.success) {
      return { title: '', description: '', image: lookResult.url, finalUrl: url, debugLog };
    }
  }

  return { title: '', description: '', image: '', finalUrl: firstResult.finalUrl, debugLog };
}

export default {
  async fetch(request, env) {
    // Only allow GET
    if (request.method !== 'GET') {
      return Response.json({ error: 'Method not allowed' }, { status: 405 });
    }

    // Image proxy: ?image_fbid={fbid} — proxies lookaside image as binary
    // Placed before auth check: these are public Facebook images, and the bot
    // (or Lark card renderer) may not send auth headers.
    const imageFbid = new URL(request.url).searchParams.get('image_fbid');
    if (imageFbid) {
      if (!/^\d+$/.test(imageFbid)) {
        return Response.json({ error: 'Invalid image_fbid (must be numeric)' }, { status: 400 });
      }
      try {
        const lookasideUrl = buildLookasideUrl(imageFbid);
        const resp = await fetch(lookasideUrl, {
          headers: { 'User-Agent': 'Twitterbot/1.0' },
          redirect: 'follow',
        });
        const contentType = resp.headers.get('Content-Type') || '';
        if (!resp.ok || !contentType.startsWith('image/')) {
          return Response.json(
            { error: `Lookaside returned ${resp.status}, Content-Type: ${contentType}` },
            { status: 502 },
          );
        }
        return new Response(resp.body, {
          headers: {
            'Content-Type': contentType,
            'Cache-Control': 'public, max-age=86400',
          },
        });
      } catch (err) {
        return Response.json({ error: err.message }, { status: 502 });
      }
    }

    // API key check (skip if API_KEY not configured)
    const apiKey = env.API_KEY;
    if (apiKey) {
      const auth = request.headers.get('Authorization') || '';
      if (auth !== `Bearer ${apiKey}`) {
        return Response.json({ error: 'Unauthorized' }, { status: 401 });
      }
    }

    const url = new URL(request.url).searchParams.get('url');
    if (!url) {
      return Response.json({ error: 'Missing ?url= or ?image_fbid= parameter' }, { status: 400 });
    }

    if (!isFacebookUrl(url)) {
      return Response.json({ error: 'Only Facebook URLs are allowed' }, { status: 403 });
    }

    const params = new URL(request.url).searchParams;
    const debug = params.get('debug') === '1';
    const raw = params.get('raw') === '1';

    // raw=1: return raw HTML from direct fetch (for debugging)
    if (raw) {
      try {
        const resp = await fetch(url, {
          headers: { 'User-Agent': 'Twitterbot/1.0' },
          redirect: 'follow',
        });
        const html = await resp.text();
        return new Response(html, {
          status: resp.status,
          headers: { 'Content-Type': 'text/html; charset=utf-8' },
        });
      } catch (err) {
        return Response.json({ error: err.message }, { status: 502 });
      }
    }

    try {
      const result = await fetchFacebookPage(url, debug);
      if (result.error) {
        return Response.json({ error: result.error, debugLog: result.debugLog }, { status: 502 });
      }
      const response = {
        title: result.title,
        description: result.description,
        image: result.image,
        finalUrl: result.finalUrl,
      };
      if (debug) response.debugLog = result.debugLog;
      return Response.json(response);
    } catch (err) {
      return Response.json({ error: err.message }, { status: 502 });
    }
  },
};
