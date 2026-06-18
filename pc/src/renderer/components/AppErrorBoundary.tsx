import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  onReset?: () => void
}

interface State {
  error: Error | null
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('App crash:', error, info.componentStack)
  }

  private reset = () => {
    this.setState({ error: null })
    this.props.onReset?.()
  }

  render() {
    if (this.state.error) {
      return (
        <div className="w-full h-full p-4 text-xs text-red-600 bg-white overflow-auto flex flex-col">
          <p className="font-semibold mb-2">Ошибка интерфейса</p>
          <pre className="whitespace-pre-wrap break-words flex-1 mb-3">{this.state.error.message}</pre>
          <button
            type="button"
            onClick={this.reset}
            className="w-full rounded-xl py-2 text-xs font-semibold bg-black text-white"
          >
            Повторить
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
