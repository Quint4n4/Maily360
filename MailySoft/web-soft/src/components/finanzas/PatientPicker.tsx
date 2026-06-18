import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, X } from 'lucide-react'

import { searchPatients, type PatientLite } from '../../api/pacientes'

interface Props {
  value: PatientLite | null
  onChange: (patient: PatientLite | null) => void
  placeholder?: string
}

export default function PatientPicker({ value, onChange, placeholder }: Props) {
  const [term, setTerm] = useState('')
  const [debounced, setDebounced] = useState('')
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const id = setTimeout(() => setDebounced(term), 300)
    return () => clearTimeout(id)
  }, [term])

  const { data, isLoading } = useQuery({
    queryKey: ['pacientes', 'search', debounced],
    queryFn: () => searchPatients(debounced),
    enabled: open && debounced.length >= 2,
  })

  if (value) {
    return (
      <div className="flex items-center justify-between gap-2 rounded-xl px-3 py-2 text-sm"
        style={{ background: 'rgba(201,162,39,0.10)', border: '1px solid rgba(201,162,39,0.35)' }}>
        <span style={{ color: '#2A241B' }}>
          {value.full_name} <span style={{ color: '#9A958C' }}>· {value.record_number}</span>
        </span>
        <button onClick={() => onChange(null)} className="p-0.5 rounded hover:bg-black/5">
          <X className="w-4 h-4" style={{ color: '#7A756C' }} />
        </button>
      </div>
    )
  }

  return (
    <div className="relative">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: '#b89a52' }} />
        <input
          className="input pl-9"
          placeholder={placeholder ?? 'Buscar paciente por nombre o expediente…'}
          value={term}
          onChange={(e) => {
            setTerm(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
        />
      </div>

      {open && debounced.length >= 2 && (
        <div
          className="absolute z-20 mt-1 w-full rounded-xl overflow-hidden shadow-lg max-h-60 overflow-y-auto"
          style={{ background: 'rgba(255,255,255,0.96)', border: '1px solid rgba(0,0,0,0.08)' }}
        >
          {isLoading && (
            <div className="px-3 py-2 text-xs" style={{ color: '#9A958C' }}>Buscando…</div>
          )}
          {!isLoading && (data?.results?.length ?? 0) === 0 && (
            <div className="px-3 py-2 text-xs" style={{ color: '#9A958C' }}>Sin resultados.</div>
          )}
          {data?.results?.map((p: PatientLite) => (
            <button
              key={p.id}
              onClick={() => {
                onChange(p)
                setOpen(false)
                setTerm('')
              }}
              className="w-full text-left px-3 py-2 text-sm hover:bg-amber-50 transition-colors"
            >
              <span style={{ color: '#2A241B' }}>{p.full_name}</span>{' '}
              <span style={{ color: '#9A958C' }}>· {p.record_number}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
