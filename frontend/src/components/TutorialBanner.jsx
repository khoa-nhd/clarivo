import { useMemo, useState } from 'react'
import { TUTORIAL_TITLE, TUTORIAL_YOUTUBE_URL } from '../config/tutorial.js'

function toYouTubeEmbedUrl(rawUrl) {
  const value = String(rawUrl || '').trim()
  if (!value) return null

  try {
    const url = new URL(value)
    const host = url.hostname.replace(/^www\./, '')
    let videoId = ''

    if (host === 'youtu.be') {
      videoId = url.pathname.split('/').filter(Boolean)[0] || ''
    } else if (host === 'youtube.com' || host === 'm.youtube.com') {
      if (url.pathname === '/watch') {
        videoId = url.searchParams.get('v') || ''
      } else {
        const parts = url.pathname.split('/').filter(Boolean)
        if (['shorts', 'embed', 'live'].includes(parts[0])) videoId = parts[1] || ''
      }
    }

    if (!videoId || !/^[A-Za-z0-9_-]{6,}$/.test(videoId)) return null
    return `https://www.youtube-nocookie.com/embed/${videoId}?rel=0&modestbranding=1`
  } catch {
    return null
  }
}

export default function TutorialBanner() {
  const [collapsed, setCollapsed] = useState(false)
  const embedUrl = useMemo(() => toYouTubeEmbedUrl(TUTORIAL_YOUTUBE_URL), [])

  // Keep the public UI clean until a tutorial URL is configured.
  if (!embedUrl) return null

  return (
    <section className={`tutorial-banner ${collapsed ? 'collapsed' : ''}`}>
      <div className="tutorial-banner-head">
        <div>
          <div className="eyebrow">Tutorial</div>
          <h2>{TUTORIAL_TITLE}</h2>
        </div>
        <button
          type="button"
          className="tutorial-toggle"
          onClick={() => setCollapsed((value) => !value)}
          aria-expanded={!collapsed}
        >
          {collapsed ? 'Show' : 'Hide'}
        </button>
      </div>

      {!collapsed && (
        <div className="tutorial-video-frame">
          <iframe
            src={embedUrl}
            title={TUTORIAL_TITLE}
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
            referrerPolicy="strict-origin-when-cross-origin"
            allowFullScreen
          />
        </div>
      )}
    </section>
  )
}
