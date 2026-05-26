import { useEffect, useRef, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Terminal as XTerm } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import { ArrowLeft } from 'lucide-react'
import '@xterm/xterm/css/xterm.css'

const WS_BASE = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`

export default function Terminal() {
  const { name } = useParams<{ name: string }>()
  const containerRef = useRef<HTMLDivElement>(null)
  const xtermRef = useRef<XTerm | null>(null)
  const fitAddonRef = useRef<FitAddon | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const containerName = name!

  const connectWebSocket = useCallback(
    (term: XTerm, fitAddon: FitAddon) => {
      const wsUrl = `${WS_BASE}/ws/containers/${containerName}/console`
      term.writeln(`\x1b[33mConnecting to ${containerName}…\x1b[0m`)

      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.binaryType = 'arraybuffer'

      ws.onopen = () => {
        term.writeln('\x1b[32mConnected.\x1b[0m\r\n')
        // Send initial terminal size
        const dims = fitAddon.proposeDimensions()
        if (dims) {
          ws.send(
            JSON.stringify({
              type: 'resize',
              cols: dims.cols,
              rows: dims.rows,
            }),
          )
        }
      }

      ws.onmessage = (event) => {
        if (typeof event.data === 'string') {
          try {
            const msg = JSON.parse(event.data) as { type: string; data?: string }
            if (msg.type === 'stdout' && msg.data) {
              term.write(atob(msg.data))
            }
          } catch {
            term.write(event.data)
          }
        } else {
          // Binary frame: raw terminal output
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

      // Forward keyboard input to WS
      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'stdin', data: btoa(data) }))
        }
      })

      return ws
    },
    [containerName],
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
    fitAddon.fit()

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
