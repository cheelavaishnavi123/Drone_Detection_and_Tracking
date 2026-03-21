import { Backdrop, Typography, Stack, LinearProgress, Box, Paper } from '@mui/material'

export default function LoadingOverlay({ open, message, progress, processed, total, etaSeconds, onCancel }: { open: boolean, message?: string, progress?: number | null, processed?: number, total?: number, etaSeconds?: number, onCancel?: () => void }) {
  return (
    <Backdrop open={open} sx={{ color: '#fff', zIndex: (theme) => theme.zIndex.drawer + 1 }}>
      <Paper sx={{ p: 4, minWidth: 320, maxWidth: 420 }}>
        <Stack spacing={2}>
          {message && (
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
              {message}
            </Typography>
          )}
          <Box>
            <LinearProgress
              variant={typeof progress === 'number' ? 'determinate' : 'indeterminate'}
              value={typeof progress === 'number' ? Math.max(0, Math.min(100, progress)) : undefined}
              sx={{ height: 10, borderRadius: 999 }}
            />
            <Stack direction="row" justifyContent="space-between" sx={{ mt: 1 }}>
              {(typeof processed === 'number' && typeof total === 'number') ? (
                <Typography variant="caption" color="text.secondary">
                  {processed}/{total} frames
                </Typography>
              ) : <span />}
              {typeof progress === 'number' && (
                <Typography variant="caption" color="text.secondary">
                  {Math.max(0, Math.min(100, Math.round(progress)))}%
                </Typography>
              )}
            </Stack>
            {typeof etaSeconds === 'number' && etaSeconds > 0 && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, textAlign: 'right' }}>
                ETA ~ {Math.ceil(etaSeconds)}s
              </Typography>
            )}
          </Box>
          {onCancel && (
            <button onClick={onCancel} style={{ alignSelf: 'flex-end', padding: '8px 12px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#ffe4e6', cursor: 'pointer' }}>
              Cancel
            </button>
          )}
        </Stack>
      </Paper>
    </Backdrop>
  )
}


