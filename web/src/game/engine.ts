// 主執行緒端的引擎介面，方法與 Python 的 Engine 一一對應
// C 呼叫全在 Worker 內依序執行，搜索中送來的請求排在搜索之後

export type Board = readonly (readonly number[])[]   // board[y][x]，黑 = 1、白 = 2
export type Point = readonly [x: number, y: number]

export type EngineRequest =
  | { type: 'reset' }
  | { type: 'aiMove'; board: Board; ai: number; roundCounter: number }
  | { type: 'isNotForbidden'; board: Board; x: number; y: number; player: number }
  | { type: 'forbiddenPoints'; board: Board }
  | { type: 'checkWin'; board: Board; player: number }

export type WorkerMessage =
  | { type: 'ready'; boardMax: number }
  | { type: 'loadError'; message: string }
  | { type: 'result'; id: number; value: unknown }
  | { type: 'error'; id: number; message: string }

type Pending = { resolve: (value: unknown) => void; reject: (reason: Error) => void }

export class Engine {
  readonly boardMax: number
  private readonly worker: Worker
  private readonly pending = new Map<number, Pending>()
  private nextId = 0

  private constructor(worker: Worker, boardMax: number) {
    this.worker = worker
    this.boardMax = boardMax
    worker.onmessage = (e: MessageEvent<WorkerMessage>) => this.settle(e.data)
  }

  // 等 WASM 載入完成才回傳，BOARD_MAX 由 getBoardMax() 讀出
  static create(): Promise<Engine> {
    const worker = new Worker(new URL('./engine.worker.ts', import.meta.url), { type: 'module' })
    return new Promise((resolve, reject) => {
      worker.onmessage = (e: MessageEvent<WorkerMessage>) => {
        const msg = e.data
        if (msg.type === 'ready') resolve(new Engine(worker, msg.boardMax))
        else if (msg.type === 'loadError') reject(new Error(msg.message))
      }
      worker.onerror = (e) => reject(new Error(e.message || 'engine worker 載入失敗'))
    })
  }

  reset(): Promise<void> {
    return this.call({ type: 'reset' })
  }

  // 範圍/空位/開局規則由 GameState 先行過濾，進到這裡的座標保證在盤內
  isNotForbidden(board: Board, x: number, y: number, player: number): Promise<boolean> {
    return this.call({ type: 'isNotForbidden', board, x, y, player })
  }

  // 黑棋下了會判負的空點
  forbiddenPoints(board: Board): Promise<Point[]> {
    return this.call({ type: 'forbiddenPoints', board })
  }

  checkWin(board: Board, player: number): Promise<boolean> {
    return this.call({ type: 'checkWin', board, player })
  }

  /* 無合法走法時回傳 [-1, -1]，呼叫端應視為和局 */
  aiMove(board: Board, ai: number, roundCounter: number): Promise<Point> {
    return this.call({ type: 'aiMove', board, ai, roundCounter })
  }

  terminate(): void {
    this.worker.terminate()
    for (const p of this.pending.values()) p.reject(new Error('engine 已終止'))
    this.pending.clear()
  }

  private call<T>(request: EngineRequest): Promise<T> {
    const id = this.nextId++
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (value: unknown) => void, reject })
      this.worker.postMessage({ id, request })
    })
  }

  private settle(msg: WorkerMessage): void {
    if (msg.type === 'ready' || msg.type === 'loadError') return
    const p = this.pending.get(msg.id)
    if (!p) return
    this.pending.delete(msg.id)
    if (msg.type === 'error') p.reject(new Error(msg.message))
    else p.resolve(msg.value)
  }
}
