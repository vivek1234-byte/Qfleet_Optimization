/** Fuel-consumption prediction with speed and fuel sweeps. */
import { ChevronDown, RefreshCw, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Area, AreaChart, Bar, BarChart, Cell, ReferenceLine } from 'recharts'

import {
  ChartFrame,
  ThemedGrid,
  ThemedLegend,
  ThemedTooltip,
  ThemedXAxis,
  ThemedYAxis,
} from '../components/charts'
import {
  Alert,
  Badge,
  Button,
  Card,
  ErrorState,
  MeterRow,
  NumberInput,
  PageHeader,
  Select,
  Skeleton,
} from '../components/ui'
import { useAsync, useFetch } from '../hooks/useApi'
import api from '../lib/api'
import { PREDICTION_PRESETS, fuelColor } from '../lib/domain'
import { num, pct, seconds, usd } from '../lib/format'

const SPEED_STEPS = 13

// Module-level fallbacks. An inline `?? []` would be a fresh array on every
// render, which makes every useMemo that depends on it recompute for nothing.
const DEFAULT_VESSEL_TYPES = ['Container', 'Bulk Carrier', 'Tanker']
const DEFAULT_FUEL_TYPES = ['HFO', 'VLSFO', 'MGO', 'LNG', 'Methanol', 'Ammonia', 'Hydrogen']
const EMPTY = []

// Presets are labelled "<vessel class> · <origin> → <destination>"; the tail is
// the route, and the class already has its own control.
const routeLabel = (preset) => preset.label.split('·').pop().trim()

export default function Prediction() {
  const modelInfo = useFetch((signal) => api.prediction.modelInfo({ signal }), [])
  const importance = useFetch((signal) => api.prediction.featureImportance({ signal }), [])
  // /predict/batch returns bare tonnages, so the CO2 and cost that follow are
  // derived here from the same fuel constants the backend uses.
  const fuels = useFetch((signal) => api.scenarios.fuels({ signal }), [])

  const predict = useAsync((signal, body) => api.prediction.predict(body, { signal }))
  const sweep = useAsync((signal, body) => api.prediction.predictBatch(body, { signal }))
  const fuelSweep = useAsync((signal, body) => api.prediction.predictBatch(body, { signal }))
  const train = useAsync((signal, body) => api.prediction.train(body, { signal }))

  const [values, setValues] = useState(PREDICTION_PRESETS[0].values)
  const [presetId, setPresetId] = useState('container')

  const vesselTypes = modelInfo.data?.vessel_types ?? DEFAULT_VESSEL_TYPES
  const fuelTypes = modelInfo.data?.fuel_types ?? DEFAULT_FUEL_TYPES
  const metrics = modelInfo.data?.metrics

  const setField = (key) => (event) => {
    const raw = event.target.value
    setValues((v) => ({ ...v, [key]: event.target.type === 'number' ? Number(raw) : raw }))
    setPresetId(null)
  }

  const selectRoute = (event) => {
    const preset = PREDICTION_PRESETS.find((p) => p.id === event.target.value)
    if (!preset) return
    setValues(preset.values)
    setPresetId(preset.id)
  }

  const fieldErrors = predict.error?.fieldMap ?? {}

  /* ---- runs -------------------------------------------------------------- */
  const runAll = useCallback(async () => {
    const base = { ...values }
    predict.run(base)

    // Speed sweep across the vessel's plausible envelope.
    const lo = Math.max(8, base.speed_knots - 6)
    const hi = base.speed_knots + 6
    const speeds = Array.from(
      { length: SPEED_STEPS },
      (_, i) => Math.round((lo + ((hi - lo) * i) / (SPEED_STEPS - 1)) * 10) / 10,
    )
    sweep.run({ voyages: speeds.map((speed_knots) => ({ ...base, speed_knots })) })

    // Same voyage on every fuel the model knows.
    fuelSweep.run({ voyages: fuelTypes.map((fuel_type) => ({ ...base, fuel_type })) })
    // `predict`/`sweep`/`fuelSweep` are stable useAsync handles.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values, fuelTypes])

  // Predict once on first load so the page is never empty.
  const modelReady = Boolean(modelInfo.data?.trained)
  useEffect(() => {
    if (modelReady) runAll()
    // Only on the first successful model load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelReady])

  /* ---- derived ----------------------------------------------------------- */
  const rmse = metrics?.rmse ?? 0
  const speedCurve = useMemo(() => {
    const rows = sweep.data?.predictions
    if (!rows?.length) return []
    const lo = Math.max(8, values.speed_knots - 6)
    const hi = values.speed_knots + 6
    const band = 1.96 * rmse
    return rows.map((row, i) => {
      const speed = Math.round((lo + ((hi - lo) * i) / (SPEED_STEPS - 1)) * 10) / 10
      // The batch endpoint returns plain tonnages rather than full prediction
      // objects, so tolerate either shape.
      const fuel = typeof row === 'number' ? row : (row.predicted_fuel_consumption ?? 0)
      return {
        speed,
        fuel,
        lower: Math.max(fuel - band, 0),
        band: 2 * band,
      }
    })
  }, [sweep.data, values.speed_knots, rmse])

  const fuelsByName = useMemo(
    () => Object.fromEntries((fuels.data ?? EMPTY).map((f) => [f.name, f])),
    [fuels.data],
  )

  const fuelBars = useMemo(() => {
    const rows = fuelSweep.data?.predictions
    if (!rows?.length) return []
    return rows.map((row, i) => {
      const name = fuelTypes[i]
      const spec = fuelsByName[name]
      const tons = typeof row === 'number' ? row : (row.predicted_fuel_consumption ?? 0)
      return {
        fuel: name,
        tons,
        co2: tons * (spec?.co2_tons_per_ton_fuel ?? 3.1),
        cost: tons * (spec?.cost_per_ton ?? 500),
      }
    })
  }, [fuelSweep.data, fuelTypes, fuelsByName])

  const topFeatures = importance.data?.features?.slice(0, 10) ?? EMPTY
  const maxImportance = topFeatures[0]?.importance ?? 1

  const result = predict.data
  // Both are optional on the wire — the backend omits the interval when the
  // model has no RMSE, and model_r2 when it has no metrics at all.
  const interval = result?.confidence_interval
  const confidence = result?.model_r2 ?? metrics?.r2
  const ciWidth = interval
    ? ((interval[1] - interval[0]) / Math.max(result.predicted_fuel_consumption, 1)) * 100
    : 0

  return (
    <>
      <PageHeader title="Fuel Prediction" description="Predict voyage fuel." />

      <div className="mx-auto max-w-xl">
        <h2 className="text-xl font-semibold tracking-tight sm:text-2xl">
          How much fuel will this voyage need?
        </h2>

        <div className="mt-6 space-y-4">
          <Select
            label="Vessel"
            value={values.vessel_type}
            onChange={setField('vessel_type')}
            options={vesselTypes.map((t) => ({ value: t, label: t }))}
            error={fieldErrors.vessel_type}
          />
          <Select label="Route" value={presetId ?? 'custom'} onChange={selectRoute}>
            {/* Editing any field in Technical details detaches the voyage from
                its preset, so the select needs somewhere to point. */}
            {!presetId && <option value="custom">Custom voyage</option>}
            {PREDICTION_PRESETS.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {routeLabel(preset)}
              </option>
            ))}
          </Select>

          <Button
            className="w-full"
            icon={Sparkles}
            loading={predict.loading || sweep.loading}
            onClick={runAll}
          >
            Predict fuel
          </Button>
        </div>

        {modelInfo.data && !modelInfo.data.trained && (
          <Alert tone="warning" title="No trained model on disk" className="mt-5">
            Run <code>python train_model.py --generate 20000</code> from the project root, or press
            Retrain in Technical details.
          </Alert>
        )}
        {predict.error && <ErrorState error={predict.error} onRetry={runAll} className="mt-5" />}

        {predict.loading ? (
          <Skeleton className="mt-8 h-16 w-56" />
        ) : (
          result && (
            <div className="mt-8">
              <p className="numeric text-6xl font-semibold leading-none tracking-tight">
                {num(result.predicted_fuel_consumption, 0)}
                <span className="text-body ml-2 text-2xl font-medium">t</span>
              </p>
              <dl
                className="mt-6 divide-y text-sm"
                style={{ borderColor: 'rgb(var(--border-subtle))' }}
              >
                {interval && (
                  <div className="flex items-baseline justify-between gap-4 py-2.5">
                    <dt className="text-faint">Expected</dt>
                    <dd className="numeric">
                      {num(interval[0], 0)}–{num(interval[1], 0)} t
                    </dd>
                  </div>
                )}
                {Number.isFinite(confidence) && (
                  <div className="flex items-baseline justify-between gap-4 py-2.5">
                    <dt className="text-faint">Confidence (R²)</dt>
                    <dd className="numeric">{pct(confidence * 100, 2)}</dd>
                  </div>
                )}
              </dl>
            </div>
          )
        )}
      </div>

      <details
        className="group mt-10 rounded-lg border"
        style={{ borderColor: 'rgb(var(--border-subtle))' }}
      >
        <summary className="expand-toggle cursor-pointer list-none [&::-webkit-details-marker]:hidden">
          Technical details
          <ChevronDown
            size={14}
            className="text-faint transition-transform group-open:rotate-180"
            aria-hidden
          />
        </summary>
        <div
          className="space-y-5 border-t p-4"
          style={{ borderColor: 'rgb(var(--border-subtle))' }}
        >
          <Card
            title="Voyage"
            description="What are we predicting"
            actions={
              <Button
                size="sm"
                variant="secondary"
                icon={RefreshCw}
                loading={train.loading}
                onClick={() =>
                  train
                    .run({ model_type: 'xgboost', test_size: 0.2, persist: true })
                    .then((res) => {
                      if (res) {
                        modelInfo.refetch()
                        importance.refetch()
                      }
                    })
                }
              >
                Retrain model
              </Button>
            }
          >
            <div className="space-y-4">
              <Select
                label="Fuel"
                value={values.fuel_type}
                onChange={setField('fuel_type')}
                options={fuelTypes.map((t) => ({ value: t, label: t }))}
                error={fieldErrors.fuel_type}
              />
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <NumberInput
                  label="Deadweight"
                  unit="t"
                  min={1000}
                  step={1000}
                  value={values.dwt}
                  onChange={setField('dwt')}
                  error={fieldErrors.dwt}
                />
                <NumberInput
                  label="Engine power"
                  unit="kW"
                  min={500}
                  step={500}
                  value={values.engine_power_kw}
                  onChange={setField('engine_power_kw')}
                  error={fieldErrors.engine_power_kw}
                />
                <NumberInput
                  label="Speed"
                  unit="kn"
                  min={5}
                  max={30}
                  step={0.5}
                  value={values.speed_knots}
                  onChange={setField('speed_knots')}
                  error={fieldErrors.speed_knots}
                />
                <NumberInput
                  label="Distance"
                  unit="nm"
                  min={50}
                  step={50}
                  value={values.distance_nm}
                  onChange={setField('distance_nm')}
                  error={fieldErrors.distance_nm}
                />
                <NumberInput
                  label="Cargo load"
                  unit="%"
                  min={0}
                  max={100}
                  value={values.cargo_load_pct}
                  onChange={setField('cargo_load_pct')}
                  error={fieldErrors.cargo_load_pct}
                />
                <NumberInput
                  label="Sea state"
                  unit="Bft"
                  min={0}
                  max={12}
                  step={0.1}
                  value={values.weather_beaufort}
                  onChange={setField('weather_beaufort')}
                  error={fieldErrors.weather_beaufort}
                />
                <NumberInput
                  label="Draft"
                  unit="m"
                  min={2}
                  max={25}
                  step={0.1}
                  value={values.draft_meters}
                  onChange={setField('draft_meters')}
                  error={fieldErrors.draft_meters}
                  className="col-span-2"
                />
              </div>
            </div>
          </Card>

          {train.error && <ErrorState error={train.error} />}
          {train.data && (
            <Alert tone="success" title="Model retrained">
              R² {num(train.data.r2, 4)} · RMSE {num(train.data.rmse, 2)} t · MAPE{' '}
              {pct(train.data.mape, 2)} on {num(train.data.n_test)} held-out voyages, in{' '}
              {seconds(train.data.train_time)}.
            </Alert>
          )}

          {result && ciWidth > 45 && (
            <Alert tone="warning" title="Wide prediction interval">
              The interval spans {pct(ciWidth, 0)} of the point estimate — inputs may sit outside
              the training distribution.
            </Alert>
          )}

          {result && (
            <dl className="divide-y text-sm" style={{ borderColor: 'rgb(var(--border-subtle))' }}>
              {[
                ['CO₂e', `${num(result.estimated_co2_tons, 1)} t`],
                ['Bunker cost', usd(result.estimated_cost_usd, { compact: true })],
              ].map(([label, value]) => (
                <div key={label} className="flex items-baseline justify-between gap-4 py-2.5">
                  <dt className="text-faint">{label}</dt>
                  <dd className="numeric">{value}</dd>
                </div>
              ))}
            </dl>
          )}

          <Card
            title="Speed sensitivity"
            description="Fuel consumption across a range of speeds for this voyage"
          >
            {sweep.loading ? (
              <Skeleton className="h-72 w-full" />
            ) : speedCurve.length ? (
              <>
                <ChartFrame height={300}>
                  <AreaChart data={speedCurve} margin={{ top: 10, right: 20, bottom: 20, left: 0 }}>
                    <defs>
                      <linearGradient id="fuelBand" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#06a3ee" stopOpacity={0.28} />
                        <stop offset="100%" stopColor="#06a3ee" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <ThemedGrid />
                    <ThemedXAxis
                      dataKey="speed"
                      unit=" kn"
                      label={{
                        value: 'Service speed (kn)',
                        position: 'insideBottom',
                        offset: -12,
                        fontSize: 12,
                      }}
                    />
                    <ThemedYAxis unit=" t" />
                    <ThemedTooltip formatter={(v, name) => [`${num(v, 1)} t`, name]} />
                    {/* Stacked: an invisible floor at the lower bound, then
                        the band itself. That draws a true interval rather
                        than a filled area under the curve. */}
                    <Area
                      type="monotone"
                      dataKey="lower"
                      stackId="ci"
                      name="Lower bound"
                      stroke="none"
                      fill="none"
                    />
                    <Area
                      type="monotone"
                      dataKey="band"
                      stackId="ci"
                      name="±1.96 × RMSE"
                      stroke="none"
                      fill="url(#fuelBand)"
                    />
                    <Area
                      type="monotone"
                      dataKey="fuel"
                      name="Predicted fuel"
                      stroke="#06a3ee"
                      strokeWidth={2.5}
                      fill="none"
                    />
                    <ReferenceLine
                      x={values.speed_knots}
                      stroke="#f59e0b"
                      strokeDasharray="4 3"
                      label={{ value: 'selected', fontSize: 11, fill: '#f59e0b', position: 'top' }}
                    />
                  </AreaChart>
                </ChartFrame>
                {speedCurve.length > 1 && (
                  <p className="text-faint mt-3 text-xs">
                    Dropping from {speedCurve[speedCurve.length - 1].speed} kn to{' '}
                    {speedCurve[0].speed} kn saves{' '}
                    <span className="numeric font-semibold">
                      {num(speedCurve[speedCurve.length - 1].fuel - speedCurve[0].fuel, 0)} t
                    </span>{' '}
                    on this voyage — at the cost of{' '}
                    {num(
                      values.distance_nm / speedCurve[0].speed -
                        values.distance_nm / speedCurve[speedCurve.length - 1].speed,
                      1,
                    )}{' '}
                    extra hours at sea.
                  </p>
                )}
              </>
            ) : (
              <p className="text-faint py-10 text-center text-sm">Run a prediction to see the curve.</p>
            )}
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card
              title="Same voyage, every fuel"
              description="Tonnage and CO₂ by fuel type"
            >
              {fuelSweep.loading ? (
                <Skeleton className="h-64 w-full" />
              ) : fuelBars.length ? (
                <ChartFrame height={260}>
                  <BarChart data={fuelBars} margin={{ top: 10, right: 10, bottom: 10, left: 0 }}>
                    <ThemedGrid />
                    <ThemedXAxis dataKey="fuel" interval={0} angle={-25} textAnchor="end" height={54} />
                    <ThemedYAxis unit=" t" />
                    <ThemedTooltip formatter={(value, name) => [`${num(value, 1)} t`, name]} />
                    <ThemedLegend />
                    <Bar dataKey="tons" name="Bunker burnt" radius={[4, 4, 0, 0]}>
                      {fuelBars.map((row) => (
                        <Cell key={row.fuel} fill={fuelColor(row.fuel)} />
                      ))}
                    </Bar>
                    <Bar
                      dataKey="co2"
                      name="CO₂e"
                      radius={[4, 4, 0, 0]}
                      fill="#94a3b8"
                      fillOpacity={0.55}
                    />
                  </BarChart>
                </ChartFrame>
              ) : (
                <p className="text-faint py-10 text-center text-sm">No data yet.</p>
              )}
            </Card>

            <Card
              title="What the model leans on"
              description="Gain-based feature importance"
              actions={
                importance.data && <Badge tone="primary">{importance.data.model_type}</Badge>
              }
            >
              {importance.loading ? (
                <Skeleton className="h-64 w-full" />
              ) : importance.error ? (
                <ErrorState error={importance.error} onRetry={importance.refetch} />
              ) : (
                <div className="space-y-2.5">
                  {topFeatures.map((f) => (
                    <MeterRow
                      key={f.feature}
                      label={f.feature.replace(/_/g, ' ')}
                      value={f.importance}
                      max={maxImportance}
                      display={pct(f.importance * 100, 1)}
                      tone="eco"
                    />
                  ))}
                  <p className="text-faint pt-1 text-xs" title="Propulsion-energy terms encode power × time and the cubic speed law from naval architecture.">
                    Engineered propulsion features dominate, as expected.
                  </p>
                </div>
              )}
            </Card>
          </div>

          <Card title="Model" description="What is loaded right now" >
            {modelInfo.loading ? (
              <Skeleton className="h-40 w-full" />
            ) : modelInfo.error ? (
              <ErrorState error={modelInfo.error} onRetry={modelInfo.refetch} />
            ) : (
              <div className="grid gap-5 sm:grid-cols-2">
                <dl className="space-y-1.5 text-sm">
                  {[
                    ['Type', modelInfo.data?.model_type],
                    ['Features', modelInfo.data?.features?.length],
                    ['Training rows', metrics && num(metrics.n_train)],
                    ['Held out', metrics && num(metrics.n_test)],
                  ].map(([label, value]) => (
                    <div key={label} className="flex justify-between gap-3">
                      <dt className="text-faint">{label}</dt>
                      <dd className="numeric">{value ?? '—'}</dd>
                    </div>
                  ))}
                </dl>
                {metrics && (
                  <dl className="space-y-1.5 text-sm">
                    {[
                      ['R²', num(metrics.r2, 4)],
                      ['RMSE', `${num(metrics.rmse, 2)} t`],
                      ['MAE', `${num(metrics.mae, 2)} t`],
                      ['MAPE', pct(metrics.mape, 2)],
                      ['Train time', seconds(metrics.train_time)],
                    ].map(([label, value]) => (
                      <div key={label} className="flex justify-between gap-3">
                        <dt className="text-faint">{label}</dt>
                        <dd className="numeric">{value}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </div>
            )}
          </Card>
        </div>
      </details>
    </>
  )
}
