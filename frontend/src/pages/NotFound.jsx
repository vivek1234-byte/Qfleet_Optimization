import { Compass } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Card, EmptyState } from '../components/ui'

export default function NotFound() {
  return (
    <Card>
      <EmptyState
        icon={Compass}
        title="Off the chart"
        description="That address is not part of the application."
        action={
          <Link
            to="/"
            className="inline-flex items-center rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700"
          >
            Back to the dashboard
          </Link>
        }
      />
    </Card>
  )
}
