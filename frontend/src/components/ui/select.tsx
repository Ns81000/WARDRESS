import * as React from "react"
import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"
import { listboxAction } from "@/lib/listbox-keys"

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

/*
 * Select-only combobox per the WAI-ARIA pattern: the trigger exposes
 * aria-expanded/aria-haspopup/aria-controls, opening moves focus to the
 * selected option, Arrow/Home/End walk the options, Enter/Space activate
 * natively, Escape closes back to the trigger and Tab closes without
 * stealing focus. Empty-string values are legal (used as "None" options).
 */
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
  const listboxId = React.useId()
  const triggerRef = React.useRef<HTMLButtonElement>(null)
  const optionRefs = React.useRef<(HTMLButtonElement | null)[]>([])
  const justOpenedRef = React.useRef(false)
  const currentOption = options.find((opt) => opt.value === value)

  const focusOption = (index: number) => {
    optionRefs.current[index]?.focus()
  }

  const openListbox = () => {
    justOpenedRef.current = true
    setIsOpen(true)
  }

  React.useEffect(() => {
    if (!isOpen || !justOpenedRef.current) return
    justOpenedRef.current = false
    const idx = Math.max(
      0,
      options.findIndex((o) => o.value === value)
    )
    focusOption(idx)
  }, [isOpen, options, value])

  // Own Escape for the whole open-menu lifetime, captured at window level
  // so parent layers (a Radix dialog listening at document capture) cannot
  // dismiss on the same keystroke.
  React.useEffect(() => {
    if (!isOpen) return
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation()
        setIsOpen(false)
        triggerRef.current?.focus()
      }
    }
    window.addEventListener("keydown", handleKeyDown, true)
    return () => {
      window.removeEventListener("keydown", handleKeyDown, true)
    }
  }, [isOpen])

  const commit = (v: string) => {
    onChange(v)
    setIsOpen(false)
    triggerRef.current?.focus()
  }

  return (
    <div className={cn("relative w-full", className)}>
      <button
        id={id}
        ref={triggerRef}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={isOpen ? listboxId : undefined}
        onClick={() => {
          if (!isOpen) {
            // Mouse-opened menus also land focus on the selected option.
            justOpenedRef.current = true
            setIsOpen(true)
          } else {
            setIsOpen(false)
          }
        }}
        onKeyDown={(e) => {
          if (!isOpen && ["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
            e.preventDefault()
            openListbox()
          }
        }}
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
          <div
            role="listbox"
            id={listboxId}
            aria-labelledby={id}
            tabIndex={-1}
            className="absolute left-0 mt-1.5 w-full rounded-md border border-hairline-strong bg-surface-card py-1 z-50 max-h-60 overflow-y-auto animate-detail-in font-mono text-code-md shadow-lg"
          >
            {options.map((opt, i) => (
              <button
                key={opt.value}
                ref={(el) => {
                  optionRefs.current[i] = el
                }}
                type="button"
                role="option"
                aria-selected={opt.value === value}
                tabIndex={-1}
                onClick={() => commit(opt.value)}
                onKeyDown={(e) => {
                  const action = listboxAction(e.key, i, options.length)
                  if (!action) return
                  e.preventDefault()
                  if (action === "commit") commit(opt.value)
                  else if (action === "dismiss") setIsOpen(false)
                  else if (action === "prev") focusOption(i - 1)
                  else if (action === "next") focusOption(i + 1)
                  else if (action === "first") focusOption(0)
                  else if (action === "last") focusOption(options.length - 1)
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
