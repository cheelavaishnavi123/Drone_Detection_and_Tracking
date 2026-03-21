import { Container, Box, Typography, Button, Stack, Paper, CssBaseline, Snackbar, Alert } from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import DownloadIcon from '@mui/icons-material/Download'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import AirplanemodeActiveIcon from '@mui/icons-material/AirplanemodeActive'
import RadarIcon from '@mui/icons-material/Radar'
import VideocamIcon from '@mui/icons-material/Videocam'
import { useMemo, useRef, useState, useEffect } from 'react'
import { ThemeProvider, createTheme } from '@mui/material/styles'
import axios from 'axios'
import UploadCard from './components/UploadCard'
import LoadingOverlay from './components/LoadingOverlay'
import Dashboard from './components/Dashboard'
import VideoPlayer from './components/videoPlayer'

// cast to any to avoid type issues if vite types aren't picked up by tooling
const API_BASE = (import.meta as any).env.VITE_API_BASE || 'http://localhost:8000'

export default function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploadedName, setUploadedName] = useState<string | null>(null)
  const [inputId, setInputId] = useState<string | null>(null)
  const [processing, setProcessing] = useState(false)
  const [progressMsg, setProgressMsg] = useState('')
  const [progress, setProgress] = useState<number | null>(null)
  const [framesProcessed, setFramesProcessed] = useState<number | null>(null)
  const [framesTotal, setFramesTotal] = useState<number | null>(null)
  const [etaSeconds, setEtaSeconds] = useState<number | null>(null)
  const [outputName, setOutputName] = useState<string | null>(null)
  const [outputId, setOutputId] = useState<string | null>(null)
  const [metricsPath, setMetricsPath] = useState<string | null>(null)
  const [metrics, setMetrics] = useState<any>(null)
  const [droneSummary, setDroneSummary] = useState<string[] | null>(null)
  const [droneSummaryError, setDroneSummaryError] = useState<string | null>(null)
  const [alertOpen, setAlertOpen] = useState(false)
  const [alertMessage, setAlertMessage] = useState('')
  const [alertSeverity, setAlertSeverity] = useState<'success' | 'info' | 'warning' | 'error'>('info')
  const [droneDetected, setDroneDetected] = useState(false)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const oscillatorRef = useRef<OscillatorNode | null>(null)
  const gainNodeRef = useRef<GainNode | null>(null)
  const pollTimerRef = useRef<number | null>(null)
  const uploadAbortRef = useRef<AbortController | null>(null)
  const [isUploading, setIsUploading] = useState(false)

  const ensureAudioContext = () => {
    try {
      if (!audioCtxRef.current) {
        // @ts-ignore - Safari prefix
        const Ctx = window.AudioContext || (window as any).webkitAudioContext
        audioCtxRef.current = new Ctx()
      }
      if (audioCtxRef.current?.state === 'suspended') {
        audioCtxRef.current.resume()
      }
    } catch {}
  }

  // Stop beep when alert is closed
  useEffect(() => {
    if (!alertOpen) {
      // Stop the continuous beep when alert closes
      if (oscillatorRef.current) {
        try {
          oscillatorRef.current.stop()
          oscillatorRef.current = null
        } catch {}
      }
      if (gainNodeRef.current) {
        try {
          gainNodeRef.current.disconnect()
          gainNodeRef.current = null
        } catch {}
      }
    }
  }, [alertOpen])

  // Start a continuous beep only when alert is open AND a drone is detected
  useEffect(() => {
    if (!alertOpen || !droneDetected) return
    try {
      ensureAudioContext()
      const ctx = audioCtxRef.current
      if (!ctx) return
      // if already beeping, skip
      if (oscillatorRef.current) return
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      gain.gain.value = 0.05
      osc.type = 'sine'
      osc.frequency.value = 880
      osc.connect(gain)
      gain.connect(ctx.destination)
      oscillatorRef.current = osc
      gainNodeRef.current = gain
      osc.start()
    } catch {}
  }, [alertOpen, droneDetected])

  const canStart = useMemo(() => !!uploadedName && !processing, [uploadedName, processing])

  const onUpload = async (file: File) => {
    ensureAudioContext()
    setSelectedFile(file)
    setProcessing(true)
    setProgressMsg('Uploading...')
    setDroneDetected(false)
    setAlertOpen(false)
    try {
      const form = new FormData()
      form.append('file', file)
      const controller = new AbortController()
      uploadAbortRef.current = controller
      setIsUploading(true)
      const res = await axios.post(`${API_BASE}/upload`, form, { headers: { 'Content-Type': 'multipart/form-data' }, signal: controller.signal })
      setUploadedName(res.data.filename)
      setInputId(res.data.input_id || null)
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Upload failed')
    } finally {
      setIsUploading(false)
      setProcessing(false)
      setProgressMsg('')
      setProgress(null)
      setFramesProcessed(null)
      setFramesTotal(null)
      setEtaSeconds(null)
    }
  }

  // Choose/Upload controls removed per request; use the UploadCard as the sole picker/uploader

  const startProcessing = async () => {
    ensureAudioContext()
    if (!uploadedName) return
    setProcessing(true)
    setProgressMsg('Analyzing Video...')
    setProgress(0)
    setFramesProcessed(0)
    setFramesTotal(null)
    setEtaSeconds(null)
    setDroneDetected(false)
    setAlertOpen(false)
    // Start polling progress while backend processes
    let pollTimer: number | null = null
    const startPolling = () => {
      if (!uploadedName) return
      const poll = async () => {
        try {
          const res = await axios.get(`${API_BASE}/progress/${uploadedName}`)
          const p = typeof res.data?.percent === 'number' ? res.data.percent : 0
          setProgress(p)
          if (typeof res.data?.processed === 'number') setFramesProcessed(res.data.processed)
          if (typeof res.data?.total === 'number') setFramesTotal(res.data.total)
          if (typeof res.data?.eta_seconds === 'number') setEtaSeconds(res.data.eta_seconds)
          // When progress hits 100, finalize to fetch metrics and IDs
          if (p >= 100) {
            if (pollTimer) { window.clearInterval(pollTimer) }
            if (pollTimerRef.current) { window.clearInterval(pollTimerRef.current as number); pollTimerRef.current = null }
            try {
              const ff = new FormData()
              ff.append('filename', uploadedName)
              if (inputId) ff.append('input_id', inputId)
              // retry finalize a few times to handle slow filesystem writes
              let fin: any = null
              for (let i = 0; i < 5; i++) {
                try {
                  fin = await axios.post(`${API_BASE}/finalize`, ff)
                  break
                } catch {
                  await new Promise(r => setTimeout(r, 800))
                }
              }
              if (fin && fin.data) {
                setOutputName(fin.data.output)
                setOutputId(fin.data.output_id || null)
                if (fin.data.metrics) {
                  setMetricsPath(fin.data.metrics)
                  try {
                    const metricsRes = await axios.get(`${API_BASE}/download/metrics/${fin.data.metrics}`)
                    const droneName = fin.data.drone_name || metricsRes.data?.drone_name || metricsRes.data?.final_classification?.class
                    const risk = classifyRisk(droneName)
                    setMetrics({
                      ...metricsRes.data,
                      video_type: fin.data.video_type,
                      drone_detected: fin.data.drone_detected ?? metricsRes.data.drone_detected ?? false,
                      detection_probability: fin.data.detection_probability ?? metricsRes.data.detection_probability ?? 0,
                      drone_name: droneName || 'Unknown',
                      harmful: risk.harmful,
                      risk_reason: risk.reason
                    })
                    // Prime Gemini summary fetch
                    setDroneSummary(null)
                    setDroneSummaryError(null)
                    // Compose alert based on detection result and type
                    try {
                      const detected = (fin.data.drone_detected ?? metricsRes.data.drone_detected) === true
                      const displayName = (droneName || fin.data.video_type || metricsRes.data.video_type || 'Unknown') as string
                      const riskStr = risk.harmful ? 'Harmful' : 'Not harmful'
                      setDroneDetected(detected)
                      setAlertSeverity(detected ? (risk.harmful ? 'error' : 'warning') : 'info')
                      setAlertMessage(detected ? `Drone detected · Type: ${displayName} · ${riskStr}` : `No drone detected · Type: ${displayName}`)
                      setAlertOpen(true)
                    } catch {}
                  } catch { setMetrics(null) }
                } else {
                  setMetrics(null)
                }
                // refresh stored videos list after successful finalize
                try {
                  const list = await axios.get(`${API_BASE}/videos`)
                  setLibrary(list.data || [])
                } catch {}
                
              }
            } catch {}
            setProcessing(false)
            setProgressMsg('')
            setProgress(null)
            setEtaSeconds(null)
          }
        } catch {}
      }
      poll()
      // @ts-ignore setInterval returns number in browsers
      pollTimer = window.setInterval(poll, 1000)
      pollTimerRef.current = pollTimer
    }
    startPolling()
    try {
      const form = new FormData()
      form.append('filename', uploadedName)
      if (inputId) form.append('input_id', inputId)
      await axios.post(`${API_BASE}/process`, form)
      // metrics and alerts are handled on finalize after progress reaches 100%
      console.log(metrics)
      // Refresh library
      try {
        const list = await axios.get(`${API_BASE}/videos`)
        setLibrary(list.data || [])
      } catch {}
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Processing failed')
    } finally {
      // do not reset here; finalize path will clear when complete or cancel will clear
    }
  }

  // Normalize drone name for better LLM results (remove ids/underscores, trim)
  const normalizeDroneName = (name?: string) => {
    if (!name) return ''
    let n = name.replace(/\s+/g, ' ').trim()
    n = n.replace(/[_\-]+/g, ' ')
    n = n.replace(/^[0-9]+\s*/g, '') // drop leading numeric ids like "21_"
    n = n.replace(/\s+pro\s*$/i, ' Pro') // make common suffixes nicer
    n = n.replace(/\s+/g, ' ').trim()
    return n
  }

  // Fetch Gemini description when metrics (and drone_name) becomes available or changes
  // Only fetch if drone is detected and video type is not IR
  useEffect(() => {
    const run = async () => {
      const name = metrics?.drone_name
      const detected = metrics?.drone_detected === true
      const videoType = metrics?.video_type
      const isIR = videoType === 'IR'
      
      // Reset state if no name
      if (!name) { 
        setDroneSummary(null); 
        setDroneSummaryError(null); 
        return 
      }
      
      // Don't call API if no drone detected
      if (!detected) {
        setDroneSummary(null)
        setDroneSummaryError('No drone detected in this video.')
        return
      }
      
      // Don't call API for IR videos
      if (isIR) {
        setDroneSummary(null)
        setDroneSummaryError('Drone description is not available for IR videos.')
        return
      }
      
      // Make API call only if drone is detected and video is not IR
      const cleaned = normalizeDroneName(name)
      try {
        const form = new FormData()
        form.append('name', cleaned)
        const desc = await axios.post(`${API_BASE}/describe-drone`, form)
        const sentences = (desc.data?.sentences as string[]) || null
        setDroneSummary(sentences)
        setDroneSummaryError(null)
      } catch (e: any) {
        setDroneSummary(null)
        setDroneSummaryError(e?.response?.data?.detail ? JSON.stringify(e.response.data.detail) : 'Failed to load drone description')
      }
    }
    run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metrics?.drone_name, metrics?.drone_detected, metrics?.video_type])

  const cancel = async () => {
    if (isUploading && uploadAbortRef.current) {
      try { uploadAbortRef.current.abort() } catch {}
      uploadAbortRef.current = null
    } else if (uploadedName) {
      try {
        const form = new FormData()
        form.append('filename', uploadedName)
        await axios.post(`${API_BASE}/cancel`, form)
      } catch {}
    }
    if (pollTimerRef.current) { window.clearInterval(pollTimerRef.current); pollTimerRef.current = null }
    setProcessing(false)
    setProgressMsg('')
    setProgress(null)
    setFramesProcessed(null)
    setFramesTotal(null)
    setEtaSeconds(null)
  }
  const [library, setLibrary] = useState<any[]>([])

  const loadLibrary = async () => {
    try {
      const res = await axios.get(`${API_BASE}/videos`)
      setLibrary(res.data || [])
    } catch {}
  }


  const download = async () => {
    const triggerDownload = (blob: Blob, suggestedName: string) => {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = suggestedName
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    }

    try {
      if (outputId) {
        const res = await axios.get(`${API_BASE}/download/video/byid/${outputId}` as string, { responseType: 'blob' })
        const name = outputName || 'processed.mp4'
        triggerDownload(res.data, name)
        return
      }
      if (!outputName) return
      const res = await axios.get(`${API_BASE}/download/video/${outputName}` as string, { responseType: 'blob' })
      triggerDownload(res.data, outputName)
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Download failed')
    }
  }

  const classifyRisk = (droneName?: string) => {
    if (!droneName) return { harmful: false, reason: 'Unknown' }
    const n = droneName.toLowerCase()
    const harmfulKeywords = ['military', 'attack', 'assault', 'kamikaze', 'fpv', 'weapon', 'combat', 'suicide', 'bomber']
    const harmfulModels = ['shahed', 'lancet', 'switchblade']
    const benignKeywords = ['toy', 'mini', 'training', 'practice', 'recreational']
    if (harmfulModels.some(m => n.includes(m))) return { harmful: true, reason: 'Known harmful model' }
    if (harmfulKeywords.some(k => n.includes(k))) return { harmful: true, reason: 'Harmful keyword match' }
    if (benignKeywords.some(k => n.includes(k))) return { harmful: false, reason: 'Benign keyword match' }
    return { harmful: false, reason: 'No harmful indicators' }
  }

  const theme = createTheme({
    palette: {
      mode: 'light',
      background: { default: '#eef5fb' },
      primary: { main: '#0ea5e9', dark: '#0284c7' },
      secondary: { main: '#10b981' },
      text: { primary: '#0f172a' }
    },
    typography: {
      fontFamily: 'Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif'
    },
    shape: {
      borderRadius: 16
    },
    components: {
      MuiPaper: {
        styleOverrides: {
          root: {
            borderRadius: '1rem',
            boxShadow: '0 10px 30px rgba(2, 132, 199, 0.08)',
            background: '#ffffff'
          }
        }
      },
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: '0.75rem',
            textTransform: 'none',
            fontWeight: 600
          }
        }
      }
    }
  })

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <div className="app-bg">
      <div className="dh-nav">
        <div className="dh-brand">
          <span style={{display:'inline-flex',alignItems:'center',gap:6}}>
            <AirplanemodeActiveIcon fontSize="small"/>
            <span>Drone Hunter</span>
          </span>
        </div>
      </div>
      <Container maxWidth="md" sx={{ py: 6, minHeight: '100dvh', display: 'flex', flexDirection: 'column', justifyContent: 'flex-start' }}>
        <Stack alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <Box className="hero-panel" sx={{ width: '100%' }}>
            <Typography className="hero-eyebrow">Upload Zone</Typography>
            <div className="hero-icons">
              <AirplanemodeActiveIcon color="primary" fontSize="small" />
              <RadarIcon color="secondary" fontSize="small" />
              <VideocamIcon color="primary" fontSize="small" />
            </div>
            <Typography className="hero-title" align="center">
              Unleash the Power of Drone Detection
            </Typography>
            <Box sx={{ my: 3 }}>
              <UploadCard onUpload={onUpload} disabled={processing} />
            </Box>
            <div className="cta-group">
              <Button className="cta-primary" variant="contained" color="primary" disabled={!canStart} onClick={startProcessing} startIcon={<PlayArrowIcon />}>Start Detection</Button>
              <Button className="cta-secondary" variant="outlined" disabled={!outputName} onClick={download} startIcon={<DownloadIcon />}>Download Result</Button>
            </div>
            <Box className="note" sx={{ mt: 1 }}><WarningAmberIcon fontSize="small" /> only videos should be uploaded</Box>
          </Box>
        </Stack>

        {/* No video preview while uploading or processing; show only final results */}
        {processing && (
          <Box sx={{ mt: 4 }}>
            <Paper sx={{ p: 3, textAlign: 'center' }}>
              <Typography variant="body1" color="text.secondary">Processing video, please wait…</Typography>
            </Paper>
          </Box>
        )}

        {!processing && (outputId || outputName) && (
          <Box sx={{ mt: 4 }}>
            <Paper className="preview-card" sx={{ p: 3 }}>
              <Typography variant="h6" gutterBottom>Preview</Typography>
              {metrics?.video_type === 'IR' && (
                <Typography variant="body2" color="warning.main" sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <WarningAmberIcon fontSize="small" /> classification of ir video is not available
                </Typography>
              )}
              <VideoPlayer videoId={outputId || undefined} fileName={outputName || undefined} />
              {/* Preview info cards removed to avoid duplication; Dashboard below shows full summary */}
            </Paper>
          </Box>
        )}

        {/* Library */}
        {!processing && (
          <Box sx={{ mt: 4 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
              <Typography variant="h6">Stored Videos</Typography>
              <Button size="small" variant="text" onClick={loadLibrary}>Refresh</Button>
            </Stack>
            {library.length === 0 ? (
              <Paper sx={{ p: 2, textAlign: 'center' }}>
                <Typography variant="body2" color="text.secondary">No stored videos yet.</Typography>
              </Paper>
            ) : (
              <Stack spacing={1}>
                {library.map((item) => (
                  <Paper key={item.id} sx={{ p: 2, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <Box>
                      <Typography variant="subtitle2">{item.output?.filename || 'processed.mp4'}</Typography>
                      <Typography variant="caption" color="text.secondary">{item.createdAt}</Typography>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                        Type: {item.video_type || 'Unknown'}
                      </Typography>
                    </Box>
                    <Stack direction="row" spacing={1}>
                      
                      {item.output?.id && (
                        <Button size="small" variant="outlined" onClick={async () => {
                          try {
                            const res = await axios.get(`${API_BASE}/download/video/byid/${item.output.id}` as string, { responseType: 'blob' })
                            const name = item.output?.filename || 'processed.mp4'
                            const url = URL.createObjectURL(res.data)
                            const a = document.createElement('a')
                            a.href = url
                            a.download = name
                            document.body.appendChild(a)
                            a.click()
                            a.remove()
                            URL.revokeObjectURL(url)
                          } catch (e: any) {
                            alert(e?.response?.data?.detail || 'Download failed')
                          }
                        }}>Download</Button>
                      )}
                    </Stack>
                  </Paper>
                ))}
              </Stack>
            )}
          </Box>
        )}

{!processing && metrics && (
  <Box sx={{ my: 2 }}>
    <Dashboard metrics={metrics} />
  </Box>
)}

{/* Drone description from Gemini */}
{!processing && metrics?.drone_name && (
  <Box sx={{ mt: 2 }}>
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>
        About “{metrics.drone_name}”
      </Typography>
      {droneSummary && (
        <ul style={{ margin: 0, paddingInlineStart: 20 }}>
          {droneSummary.map((s, i) => (
            <li key={i} style={{ marginBottom: 6 }}>
              <Typography variant="body2">{s}</Typography>
            </li>
          ))}
        </ul>
      )}
      {!droneSummary && !droneSummaryError && (
        <Typography variant="body2" color="text.secondary">
          Loading description...
        </Typography>
      )}
      {droneSummaryError && (
        <Typography 
          variant="body2" 
          color={
            droneSummaryError.includes('No drone detected') || 
            droneSummaryError.includes('not available for IR videos')
              ? 'text.secondary' 
              : 'error'
          }
        >
          {droneSummaryError}
        </Typography>
      )}
    </Paper>
  </Box>
)}


        <LoadingOverlay 
          open={processing} 
          message={progressMsg || 'Processing video, please wait…'} 
          progress={progress ?? undefined}
          processed={framesProcessed ?? undefined}
          total={framesTotal ?? undefined}
          etaSeconds={etaSeconds ?? undefined}
          onCancel={cancel}
        />
        <Snackbar 
          open={alertOpen} 
          onClose={() => setAlertOpen(false)} 
          anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
        >
          <Alert 
            onClose={() => setAlertOpen(false)} 
            severity={alertSeverity} 
            variant="filled" 
            sx={{ width: '100%' }}
          >
            {alertMessage || 'Detection Status'}
          </Alert>
        </Snackbar>
      </Container>
      </div>
    </ThemeProvider>
  )
}


