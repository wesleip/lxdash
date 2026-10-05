import { useEffect, useRef, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Terminal as XTerm } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import { ArrowLeft } from 'lucide-react'
import '@xterm/xterm/css/xterm.css'
import { useAuthStore } from '@/store/auth'
import { useActiveHostId } from '@/lib/hooks/useHosts'

const WS_BASE = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`

export default function Terminal() {
  const { name } = useParams<{ name: string }>()
  const token = useAuthStore((s) => s.token)
  const hostId = useActiveHostId()
  const containerRef = useRef<HTMLDivElement>(null)
  const xtermRef = useRef<XTerm | null>(null)
  const fitAddonRef = useRef<FitAddon | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const containerName = name!

  const connectWebSocket = useCallback(
    (term: XTerm, fitAddon: FitAddon) => {
      // Browsers cannot set headers on a WebSocket upgrade, so the JWT rides
      // in the query string — the backend closes with 1008 when it is missing.
      const params = new URLSearchParams({ token: token ?? '' })
      if (hostId !== null) {
        params.set('host_id', String(hostId))
      }
      const wsUrl = `${WS_BASE}/ws/containers/${encodeURIComponent(containerName)}/console?${params}`
      term.writeln(`\x1b[33mConnecting to ${containerName}…\x1b[0m`)

      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.binaryType = 'arraybuffer'

      ws.onopen = () => {
        term.writeln('\x1b[32mConnected.\x1b[0m\r\n')
        const dims = fitAddon.proposeDimensions()
        if (dims) {
          // Resize is a small JSON frame; keystrokes go as raw bytes for
          // zero overhead per character.
          ws.send(JSON.stringify({ type: 'resize', cols: dims.cols, rows: dims.rows }))
        } else {
          // The container may not have been laid out yet when the WS
          // opens; send a placeholder resize after a tick so the backend
          // has *something* to apply (defaults are 80x24 otherwise).
          setTimeout(() => {
            const d = fitAddon.proposeDimensions()
            if (d) {
              ws.send(JSON.stringify({ type: 'resize', cols: d.cols, rows: d.rows }))
            }
          }, 50)
        }
      }

      ws.onmessage = (event) => {
        // The backend forwards container stdout/stderr as raw binary
        // frames; treat both shapes the same way — write to xterm.js.
        if (typeof event.data === 'string') {
          term.write(event.data)
        } else {
          term.write(new Uint8Array(event.data as ArrayBuffer))
        }
      }

      ws.onclose = (ev) => {
        term.writeln(
          `\r\n\x1b[31mConnection closed (${ev.code}${ev.reason ? `: ${ev.reason}` : ''}).\x1b[0m`,
        )
      }

      ws.onerror = () => {
        term.writeln('\r\n\x1b[31mWebSocket error. Check that the container is running.\x1b[0m')
      }

      // Forward keystrokes to the container as raw bytes.
      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(new TextEncoder().encode(data))
        }
      })

      return ws
    },
    [containerName, hostId, token],
  )

  useEffect(() => {
    if (!containerRef.current) return

    const term = new XTerm({
      theme: {
        background: '#0d1117',
        foreground: '#c9d1d9',
        cursor: '#58a6ff',
        selectionBackground: '#264f78',
        black: '#484f58',
        red: '#ff7b72',
        green: '#3fb950',
        yellow: '#d29922',
        blue: '#58a6ff',
        magenta: '#bc8cff',
        cyan: '#39c5cf',
        white: '#b1bac4',
        brightBlack: '#6e7681',
        brightRed: '#ffa198',
        brightGreen: '#56d364',
        brightYellow: '#e3b341',
        brightBlue: '#79c0ff',
        brightMagenta: '#d2a8ff',
        brightCyan: '#56d4dd',
        brightWhite: '#f0f6fc',
      },
      fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", monospace',
      fontSize: 14,
      lineHeight: 1.4,
      cursorBlink: true,
      cursorStyle: 'bar',
      scrollback: 5000,
      convertEol: true,
    })

    const fitAddon = new FitAddon()
    const webLinksAddon = new WebLinksAddon()

    term.loadAddon(fitAddon)
    term.loadAddon(webLinksAddon)
    term.open(containerRef.current)
    // The container may not have its final layout yet on first paint
    // (the ``dimensions`` property only resolves after a layout pass).
    // Defer the first fit to the next animation frame so we have a real
    // viewport, and tolerate the proposal coming back null on the very
    // first render of a hidden panel.
    requestAnimationFrame(() => {
      try {
        fitAddon.fit()
      } catch (err) {
        console.warn("terminal.fit.fit failed", err)
      }
    })

    xtermRef.current = term
    fitAddonRef.current = fitAddon

    const ws = connectWebSocket(term, fitAddon)

    // Resize observer: re-fit terminal when the container resizes
    const resizeObserver = new ResizeObserver(() => {
      fitAddon.fit()
      if (ws.readyState === WebSocket.OPEN) {
        const dims = fitAddon.proposeDimensions()
        if (dims) {
          ws.send(JSON.stringify({ type: 'resize', cols: dims.cols, rows: dims.rows }))
        }
      }
    })
    resizeObserver.observe(containerRef.current)

    return () => {
      resizeObserver.disconnect()
      ws.close()
      term.dispose()
      xtermRef.current = null
      fitAddonRef.current = null
      wsRef.current = null
    }
  }, [connectWebSocket])

  return (
    <div className="flex flex-col h-full -m-6">
      {/* Header bar */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border bg-background shrink-0">
        <Link
          to={`/containers/${containerName}`}
          className="text-muted-foreground hover:text-foreground"
          aria-label="Back"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <span className="text-sm font-medium">
          Console — <span className="font-mono text-primary">{containerName}</span>
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-success animate-pulse" />
          <span className="text-xs text-muted-foreground">Connected</span>
        </div>
      </div>

      {/* Terminal viewport */}
      <div
        ref={containerRef}
        className="flex-1 p-2 bg-[#0d1117] overflow-hidden"
        aria-label={`Terminal for ${containerName}`}
      />
    </div>
  )
}
