import { useEffect, useRef, useState } from 'react'
import { Engine, type Board, type Point } from './game/engine'

// 暫時的驗證頁：quiet-8 局面跑 aiMove，旁邊的計數器確認搜索中主執行緒沒有凍結

// 同 _bench/lib/positions.py 的 QUIET_OFFSETS["quiet-8"]，(dx, dy, player) 對中心的偏移
const QUIET_8: readonly (readonly [number, number, number])[] = [
  [0, 0, 1], [1, 1, 2], [-2, 1, 1], [2, -1, 2],
  [-1, 3, 1], [3, -2, 2], [-3, -2, 1], [1, 4, 2],
]

function quiet8Board(boardMax: number): Board {
  const c = Math.floor(boardMax / 2)
  const board = Array.from({ length: boardMax }, () => new Array<number>(boardMax).fill(0))
  for (const [dx, dy, p] of QUIET_8) board[c + dy][c + dx] = p
  return board
}

function FrameCounter() {
  const [frames, setFrames] = useState(0)
  useEffect(() => {
    let handle = requestAnimationFrame(function tick() {
      setFrames((n) => n + 1)
      handle = requestAnimationFrame(tick)
    })
    return () => cancelAnimationFrame(handle)
  }, [])
  return <p>畫面更新：<span data-testid="frames">{frames}</span></p>
}

export default function App() {
  const engineRef = useRef<Engine | null>(null)
  const [boardMax, setBoardMax] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState('')

  useEffect(() => {
    let engine: Engine | null = null
    let cancelled = false
    Engine.create().then(
      (e) => {
        if (cancelled) return e.terminate()
        engine = e
        engineRef.current = e
        setBoardMax(e.boardMax)
        console.log('getBoardMax()', e.boardMax)
      },
      (err: Error) => setResult(`引擎載入失敗：${err.message}`),
    )
    return () => {
      cancelled = true
      engine?.terminate()
      engineRef.current = null
    }
  }, [])

  async function runQuiet8() {
    const engine = engineRef.current
    if (!engine) return
    setBusy(true)
    setResult('搜索中…')
    try {
      await engine.reset()
      const start = performance.now()
      const [x, y]: Point = await engine.aiMove(quiet8Board(engine.boardMax), 1, 9)
      const ms = Math.round(performance.now() - start)
      setResult(`(${x}, ${y})，${ms} ms`)
    } catch (err) {
      setResult(`失敗：${(err as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main>
      <h1>引擎驗證</h1>
      <p>BOARD_MAX：{boardMax ?? '載入中'}</p>
      <button onClick={runQuiet8} disabled={boardMax === null || busy}>quiet-8 aiMove</button>
      <p>結果：<span data-testid="result">{result}</span></p>
      <FrameCounter />
    </main>
  )
}
