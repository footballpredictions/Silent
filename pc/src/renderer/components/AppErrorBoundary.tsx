import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
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

  render() {
    if (this.state.error) {
      return (
        <div className="w-full h-full p-4 text-xs text-red-600 bg-white overflow-auto">
          <p className="font-semibold mb-2">Ошибка интерфейса</p>
          <pre className="whitespace-pre-wrap break-words">{this.state.error.message}</pre>
        </div>
      )
    }
    return this.props.children
  }
}
