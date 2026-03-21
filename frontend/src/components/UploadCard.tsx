import { Paper, Box, Typography } from '@mui/material'
import { useCallback, useState } from 'react'

type Props = {
  onUpload: (file: File) => void
  disabled?: boolean
}

export default function UploadCard({ onUpload, disabled }: Props) {
  const [dragOver, setDragOver] = useState(false)

  const handleFiles = useCallback((files: FileList | null) => {
    if (!files || !files.length) return
    const file = files[0]
    const ext = file.name.toLowerCase()
    // block images explicitly with clearer message
    if (file.type && file.type.startsWith('image/')) {
      alert('upload video format')
      return
    }
    if (!/(\.mp4|\.avi|\.mov)$/.test(ext)) {
      alert('upload video format')
      return
    }
    onUpload(file)
  }, [onUpload])

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 4,
        textAlign: 'center',
        borderStyle: dragOver ? 'solid' : 'dashed',
        borderColor: dragOver ? 'primary.main' : 'divider',
        borderWidth: 2,
        transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
        boxShadow: dragOver ? '0 6px 24px rgba(0,0,0,0.12)' : '0 4px 20px rgba(0,0,0,0.08)'
      }}
      onDragOver={(e) => { e.preventDefault(); if (!disabled) setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => { e.preventDefault(); setDragOver(false); if (!disabled) handleFiles(e.dataTransfer.files) }}
    >
      <Typography variant="h6" gutterBottom>
        Drag & Drop your video here
      </Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        or click to choose a file
      </Typography>

      <Box sx={{ mt: 2 }}>
        <input
          type="file"
          accept="video/mp4,video/avi,video/quicktime"
          onChange={(e) => handleFiles(e.target.files)}
          disabled={!!disabled}
        />
      </Box>
    </Paper>
  )
}


