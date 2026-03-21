import React, { useMemo, useRef, useState } from "react";

type VideoPlayerProps = {
  videoId?: string;       // GridFS ID (if available)
  fileName?: string;      // Fallback: output filename on disk
};

const API_BASE = (import.meta as any).env.VITE_API_BASE || 'http://localhost:8000'

const VideoPlayer: React.FC<VideoPlayerProps> = ({ videoId, fileName }: VideoPlayerProps) => {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)

  const src = useMemo(() => {
    if (videoId) return `${API_BASE}/download/video/byid/${videoId}`
    if (fileName) return `${API_BASE}/download/video/${fileName}`
    return ''
  }, [videoId, fileName])

  const onPlay = async () => {
    try {
      await videoRef.current?.play()
      setIsPlaying(true)
    } catch {}
  }

  const onPause = () => {
    try { videoRef.current?.pause() } catch {}
    setIsPlaying(false)
  }

  return (
    <div style={{ width: '100%' }}>
      <video
        ref={videoRef}
        controls
        width="100%"
        preload="metadata"
        crossOrigin="anonymous"
        style={{ borderRadius: 12 }}
        onError={() => {
          // Basic fallback: toggle src to force reload if needed
          try {
            const v = videoRef.current
            if (v && src) {
              v.load()
            }
          } catch {}
        }}
        key={src}
      >
        {src && <source src={src} type="video/mp4" />}
      </video>
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <button onClick={onPlay} disabled={isPlaying} style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #cbd5e1', background: isPlaying ? '#e2e8f0' : '#e0f2fe', cursor: isPlaying ? 'default' : 'pointer' }}>Play</button>
        <button onClick={onPause} disabled={!isPlaying} style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #cbd5e1', background: !isPlaying ? '#e2e8f0' : '#fee2e2', cursor: !isPlaying ? 'default' : 'pointer' }}>Pause</button>
      </div>
    </div>
  );
};

export default VideoPlayer;
  