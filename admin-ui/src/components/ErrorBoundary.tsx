import { Component, type ReactNode } from 'react'

type Props = { children: ReactNode }
type State = { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center p-6">
          <div className="max-w-md w-full bg-[#111] border border-[#222] rounded-2xl p-6 text-center">
            <h1 className="text-lg font-semibold text-white mb-2">Ошибка интерфейса</h1>
            <p className="text-sm text-[#888] mb-4">{this.state.error.message}</p>
            <button
              type="button"
              onClick={() => {
                localStorage.removeItem('admin_token')
                window.location.href = '/'
              }}
              className="bg-white text-black rounded-lg px-4 py-2 text-sm font-medium"
            >
              Сбросить и войти заново
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
