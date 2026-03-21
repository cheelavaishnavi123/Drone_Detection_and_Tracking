import { Paper, Typography, Grid, Box } from '@mui/material'

export default function Dashboard({ metrics }: { metrics: any }) {
  const track = metrics?.average_tracking_time_sec ?? 0
  const detect = metrics?.average_detection_time_sec ?? 0
  const clsName = metrics?.final_classification?.class ?? 'N/A'
  const clsConf = metrics?.final_classification?.confidence ?? null
  const videoType = metrics?.video_type ?? 'Unknown'
  const droneDetected = metrics?.drone_detected ?? false
  const detectionProbability = metrics?.detection_probability ?? 0
  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>Summary</Typography>
      <Grid container spacing={2}>
        <Grid item xs={12} md={3}>
          <Stat label="Video Type" value={videoType} />
        </Grid>
        <Grid item xs={12} md={3}>
          <Stat label="Drone Detected" value={droneDetected ? 'Yes' : 'No'} />
        </Grid>
        <Grid item xs={12} md={3}>
          <Stat label="Detection Probability" value={`${detectionProbability}%`} />
        </Grid>
        <Grid item xs={12} md={3}>
          <Stat label="Avg Detection (s/frame)" value={detect.toFixed(4)} />
        </Grid>
        <Grid item xs={12} md={3}>
          <Stat label="Avg Tracking (s/frame)" value={track.toFixed(4)} />
        </Grid>
        <Grid item xs={12} md={3}>
          <Stat label="Classification" value={clsConf != null ? `${clsName} (${clsConf.toFixed(2)})` : 'None'} />
        </Grid>
      </Grid>
    </Paper>
  )
}

function Stat({ label, value }: { label: string, value: string }) {
  return (
    <Box>
      <Typography variant="overline" color="text.secondary">{label}</Typography>
      <Typography variant="h5">{value}</Typography>
    </Box>
  )
}


