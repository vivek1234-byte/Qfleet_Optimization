/**
 * Catches render-time crashes so one broken chart cannot blank the whole app.
 *
 * The original app had no boundary at all: a single undefined field in an API
 * response took the entire UI to a white screen with nothing but a console
 * error to go on.
 */
import { AlertTriangle, RotateCcw } from 'lucide-react'
import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('Unhandled UI error:', error, info)
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div className="grid min-h-screen place-items-center p-6">
        <div className="card w-full max-w-lg p-8 text-center">
          <div className="mx-auto mb-4 w-fit rounded-full bg-rose-50 p-3 dark:bg-rose-950">
            <AlertTriangle className="text-rose-600 dark:text-rose-400" size={24} />
          </div>
          <h1 className="text-lg font-semibold">This screen hit an unexpected error</h1>
          <p className="text-body mt-2 text-sm">
            The rest of the application is still fine — reload to get back to it.
          </p>
          <pre className="mt-4 max-h-40 overflow-auto rounded-lg bg-[rgb(var(--surface-sunken))] p-3 text-left text-xs">
            {String(this.state.error?.message || this.state.error)}
          </pre>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-5 inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700"
          >
            <RotateCcw size={16} />
            Reload
          </button>
        </div>
      </div>
    )
  }
}
