import * as React from "react"
import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"

export interface SelectOption {
  value: string
  label: string
}

export interface CustomSelectProps {
  id?: string
  value: string
  onChange: (value: string) => void
  options: SelectOption[]
  className?: string
  disabled?: boolean
  placeholder?: string
}

export function CustomSelect({
  id,
  value,
  onChange,
  options,
  className,
  disabled,
  placeholder = "Select...",
}: CustomSelectProps) {
  const [isOpen, setIsOpen] = React.useState(false)
  const currentOption = options.find((opt) => opt.value === value)

  React.useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setIsOpen(false)
      }
    }
    if (isOpen) {
      window.addEventListener("keydown", handleKeyDown)
    }
    return () => {
      window.removeEventListener("keydown", handleKeyDown)
    }
  }, [isOpen])

  return (
    <div className={cn("relative w-full", className)}>
      <button
        id={id}
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen((prev) => !prev)}
        className={cn(
          "w-full h-10 rounded-md border border-hairline-strong bg-surface-card px-3.5 py-2.5 text-left text-body-sm text-ink outline-none transition-all flex items-center justify-between cursor-pointer select-none",
          "focus-visible:border-ink focus:border-ink",
          "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
          "active:enabled:scale-[0.98] duration-150"
        )}
      >
        <span className="truncate">{currentOption ? currentOption.label : placeholder}</span>
        <ChevronDown
          className={cn(
            "size-4 text-charcoal transition-transform duration-200 shrink-0 ml-2",
            isOpen && "rotate-180"
          )}
        />
      </button>

      {isOpen && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
          <div className="absolute left-0 mt-1.5 w-full rounded-md border border-hairline-strong bg-surface-card py-1 z-50 max-h-60 overflow-y-auto animate-detail-in font-mono text-code-md shadow-lg">
            {options.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => {
                  onChange(opt.value)
                  setIsOpen(false)
                }}
                className={cn(
                  "w-full text-left px-3.5 py-2 cursor-pointer transition-colors text-charcoal hover:bg-white/[0.04] hover:text-ink flex items-center justify-between",
                  opt.value === value && "text-ink bg-white/[0.02] font-medium"
                )}
              >
                <span className="truncate">{opt.label}</span>
                {opt.value === value && (
                  <span className="size-1.5 rounded-full bg-accent-blue shrink-0 ml-2" />
                )}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
