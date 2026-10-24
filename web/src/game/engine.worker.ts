// Worker 端：載入 WASM 並代為呼叫 C 函數
// C 端的增量索引與置換表是全域變數，所有請求經 queue 串成一條，同一時間只跑一個 C 呼叫

import createEngine, { type EngineModule } from '../wasm/engine.mjs'
import wasmUrl from '../wasm/engine.wasm?url'
import type { Board, EngineRequest, Point, WorkerMessage } from './engine'

let mod: EngineModule
let boardMax = 0
let boardPtr = 0   // BOARD_MAX x BOARD_MAX 個 int32
let outPtr = 0     // aiRound 的 bestx、besty

function post(msg: WorkerMessage): void {
  self.postMessage(msg)
}

// 記憶體成長後 HEAP32 會換成新的 view，每次都從 mod 重新取
function writeBoard(board: Board): void {
  const heap = mod.HEAP32
  const base = boardPtr >> 2
  for (let y = 0; y < boardMax; y++) {
    for (let x = 0; x < boardMax; x++) heap[base + y * boardMax + x] = board[y][x]
  }
}

function handle(req: EngineRequest): unknown {
  switch (req.type) {
    case 'reset':
      mod._initZobristTable()
      mod._initTranspositionTable()
      return undefined
    case 'aiMove': {
      writeBoard(req.board)
      mod._aiRound(boardPtr, req.ai, req.roundCounter, outPtr, outPtr + 4)
      const heap = mod.HEAP32
      const move: Point = [heap[outPtr >> 2], heap[(outPtr >> 2) + 1]]
      return move
    }
    case 'isNotForbidden':
      writeBoard(req.board)
      return mod._checkUnValid(boardPtr, req.x, req.y, req.player) === 1
    case 'forbiddenPoints': {
      writeBoard(req.board)
      const points: Point[] = []
      for (let y = 0; y < boardMax; y++) {
        for (let x = 0; x < boardMax; x++) {
          if (req.board[y][x] === 0 && mod._checkUnValid(boardPtr, x, y, 1) !== 1) points.push([x, y])
        }
      }
      return points
    }
    case 'checkWin':
      writeBoard(req.board)
      return mod._checkWin(boardPtr, 0, boardMax - 1, 0, boardMax - 1, req.player) !== 0
  }
}

const errorMessage = (e: unknown) => (e instanceof Error ? e.message : String(e))

const ready = createEngine({ locateFile: () => wasmUrl }).then(
  (m) => {
    mod = m
    boardMax = mod._getBoardMax()
    boardPtr = mod._malloc(boardMax * boardMax * 4)
    outPtr = mod._malloc(8)
    post({ type: 'ready', boardMax })
  },
  (e) => {
    post({ type: 'loadError', message: `WASM 載入失敗：${errorMessage(e)}` })
    throw e
  },
)

let queue: Promise<void> = ready.catch(() => {})

self.onmessage = (e: MessageEvent<{ id: number; request: EngineRequest }>) => {
  const { id, request } = e.data
  queue = queue.then(() => ready).then(
    () => {
      try {
        post({ type: 'result', id, value: handle(request) })
      } catch (err) {
        post({ type: 'error', id, message: errorMessage(err) })
      }
    },
    () => post({ type: 'error', id, message: 'WASM 未載入' }),
  )
}
