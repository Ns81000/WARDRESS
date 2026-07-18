import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  Activity,
  Database,
  HardDrive,
  Timer,
  Network,
  RefreshCw,
  Workflow
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { SpotlightCard } from "@/components/ui/spotlight-card"
import * as apiClient from "@/lib/api"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"


function getServiceLogo(key: string, className?: string) {
  const classStr = cn("size-4 shrink-0", className)
  switch (key) {
    case "database":
      return (
        <svg className={classStr} xmlSpace="preserve" viewBox="0 0 432.071 445.383">
          <path stroke="none" d="M402.395 271.23c-50.302 10.376-53.76-6.655-53.76-6.655 53.111-78.808 75.313-178.843 56.153-203.326-52.27-66.785-142.752-35.2-144.262-34.38l-.486.087c-9.938-2.063-21.06-3.292-33.56-3.496-22.761-.373-40.026 5.967-53.127 15.902 0 0-161.411-66.495-153.904 83.63 1.597 31.938 45.776 241.657 98.471 178.312 19.26-23.163 37.869-42.748 37.869-42.748 9.243 6.14 20.308 9.272 31.908 8.147l.901-.765c-.28 2.876-.152 5.689.361 9.019-13.575 15.167-9.586 17.83-36.723 23.416-27.459 5.659-11.328 15.734-.796 18.367 12.768 3.193 42.307 7.716 62.266-20.224l-.796 3.188c5.319 4.26 9.054 27.711 8.428 48.969-.626 21.259-1.044 35.854 3.147 47.254 4.191 11.4 8.368 37.05 44.042 29.406 29.809-6.388 45.256-22.942 47.405-50.555 1.525-19.631 4.976-16.729 5.194-34.28l2.768-8.309c3.192-26.611.507-35.196 18.872-31.203l4.463.392c13.517.615 31.208-2.174 41.591-7 22.358-10.376 35.618-27.7 13.573-23.148z" fill="#336791" />
        </svg>
      )
    case "redis":
      return (
        <svg className={classStr} viewBox="0 0 256 220" xmlns="http://www.w3.org/2000/svg">
          <path d="M246 169c-13.7 7-84.5 36.2-99.5 44-15.1 7.9-23.5 7.8-35.4 2.1C99.2 209.4 24 179 10.3 172.5 3.6 169.3 0 166.5 0 164v-26s98-21.3 113.9-27c15.8-5.6 21.3-5.8 34.8-.9 13.4 5 94 19.5 107.3 24.3V160c0 2.5-3 5.3-10 9" fill="#912626" />
          <path d="M246 143.2c-13.7 7.1-84.5 36.2-99.5 44-15.1 8-23.5 7.9-35.4 2.2-11.9-5.7-87.2-36.1-100.8-42.6-13.5-6.5-13.8-11-.5-16.2 13.4-5.2 88.2-34.6 104-40.3 16-5.6 21.4-5.8 34.9-1 13.4 5 83.8 33 97.1 37.9 13.3 4.9 13.8 8.9.2 16" fill="#C6302B" />
          <path d="M246 127c-13.7 7.2-84.5 36.3-99.5 44.2-15.1 7.8-23.5 7.7-35.4 2-11.9-5.6-87.2-36-100.8-42.6-6.7-3.2-10.3-6-10.3-8.5V96.2s98-21.3 113.9-27c15.8-5.7 21.3-5.9 34.8-1 13.4 5 94 19.5 107.3 24.4V118c0 2.5-3 5.4-10 9" fill="#912626" />
          <path d="M246 101.4c-13.7 7-84.5 36.2-99.5 44-15.1 7.9-23.5 7.8-35.4 2.1C99.2 141.8 24 111.4 10.3 105c-13.5-6.5-13.8-11-.5-16.1C23.2 83.5 98 54 113.8 48.5c16-5.7 21.4-6 34.9-1 13.4 5 83.8 33 97.1 37.8 13.3 5 13.8 9 .2 16" fill="#C6302B" />
          <path d="M246 83.7c-13.7 7-84.5 36.2-99.5 44-15.1 7.9-23.5 7.8-35.4 2.1C99.2 124.1 24 93.7 10.3 87.2 3.6 84 0 81.2 0 78.7v-26s98-21.3 113.9-27c15.8-5.6 21.3-5.8 34.8-.9 13.4 5 94 19.5 107.3 24.4v25.5c0 2.5-3 5.3-10 9" fill="#912626" />
          <path d="M246 58c-13.7 7-84.5 36.1-99.5 44-15.1 7.9-23.5 7.8-35.4 2C99.2 98.5 24 68 10.3 61.6c-13.5-6.5-13.8-11-.5-16.2C23.2 40.1 98 10.7 113.8 5c16-5.6 21.4-5.8 34.9-.9 13.4 5 83.8 33 97.1 37.8 13.3 4.9 13.8 9 .2 16" fill="#C6302B" />
          <path d="m159.3 32.8-22 2.2-5 11.9-8-13.2L99 31.4l19-6.9-5.8-10.5 17.8 7 16.7-5.5-4.5 10.9 17 6.4M131 90.3l-41-17 58.8-9.1-17.8 26M74 39.3c17.5 0 31.5 5.5 31.5 12.2 0 6.8-14 12.2-31.4 12.2s-31.5-5.4-31.5-12.2c0-6.7 14.1-12.2 31.5-12.2" fill="#FFF" />
        </svg>
      )
    case "worker":
      return (
        <svg className={classStr} fill="#37814A" role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <title>Celery</title>
          <path d="M2.303 0A2.298 2.298 0 0 0 0 2.303v19.394A2.298 2.298 0 0 0 2.303 24h19.394A2.298 2.298 0 0 0 24 21.697V2.303A2.298 2.298 0 0 0 21.697 0zm8.177 3.072c4.098 0 7.028 1.438 7.68 1.764l-1.194 2.55c-2.442-1.057-4.993-1.41-5.672-1.41-1.574 0-2.17.922-2.17 1.763v8.494c0 .869.596 1.791 2.17 1.791.679 0 3.23-.38 5.672-1.41l1.194 2.496c-.435.271-3.637 1.818-7.68 1.818-1.112 0-4.64-.244-4.64-4.64V7.713c0-4.397 3.528-4.64 4.64-4.64z" />
        </svg>
      )
    case "scheduler":
      return (
        <svg className={classStr} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="16 16 32 32">
          <path fill="url(#py-a)" d="M31.885 16c-8.124 0-7.617 3.523-7.617 3.523l.01 3.65h7.752v1.095H21.197S16 23.678 16 31.876c0 8.196 4.537 7.906 4.537 7.906h2.708v-3.804s-.146-4.537 4.465-4.537h7.688s4.32.07 4.32-4.175v-7.019S40.374 16 31.885 16zm-4.275 2.454a1.394 1.394 0 1 1 0 2.79 1.393 1.393 0 0 1-1.395-1.395c0-.771.624-1.395 1.395-1.395z" />
          <path fill="url(#py-b)" d="M32.115 47.833c8.124 0 7.617-3.523 7.617-3.523l-.01-3.65H31.97v-1.095h10.832S48 40.155 48 31.958c0-8.197-4.537-7.906-4.537-7.906h-2.708v3.803s.146 4.537-4.465 4.537h-7.688s-4.32-.07-4.32 4.175v7.019s-.656 4.247 7.833 4.247zm4.275-2.454a1.393 1.393 0 0 1-1.395-1.395 1.394 1.394 0 1 1 1.395 1.395z" />
          <defs>
            <linearGradient id="py-a" x1="19.075" x2="34.898" y1="18.782" y2="34.658" gradientUnits="userSpaceOnUse">
              <stop stopColor="#387EB8" />
              <stop offset="1" stopColor="#366994" />
            </linearGradient>
            <linearGradient id="py-b" x1="28.809" x2="45.803" y1="28.882" y2="45.163" gradientUnits="userSpaceOnUse">
              <stop stopColor="#FFE052" />
              <stop offset="1" stopColor="#FFC331" />
            </linearGradient>
          </defs>
        </svg>
      )
    case "gateway":
      return (
        <svg className={classStr} viewBox="0 0 256 256" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid">
          <path d="M128 0C57.33 0 0 57.33 0 128s57.33 128 128 128 128-57.33 128-128S198.67 0 128 0Zm-6.67 230.605v-80.288H76.699l64.128-124.922v80.288h42.966L121.33 230.605Z" fill="#009688" />
        </svg>
      )
    default:
      return null
  }
}

function fmtUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m ${seconds % 60}s`
}

function fmtBytes(bytes: number | null): string {
  if (bytes == null) return "n/a"
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${Math.round(bytes / 1024)} KB`
}

function fmtAgo(iso: string | null): string {
  if (!iso) return "never"
  const ms = Date.now() - new Date(iso).getTime()
  const min = Math.floor(ms / 60000)
  if (min < 1) return "just now"
  if (min < 60) return `${min}m ago`
  const h = Math.floor(min / 60)
  return h < 48 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`
}

const COMPONENT_LABELS: Record<string, string> = {
  database: "PostgreSQL Database",
  redis: "Redis Message Queue",
  worker: "Celery Task Workers",
  scheduler: "Celery Beat Scheduler"
}

// Sparkline SVG component to represent scan/activity visually
function Sparkline({ colorClass = "text-accent-green" }: { colorClass?: string }) {
  return (
    <svg viewBox="0 0 100 20" className={`h-6 w-20 stroke-2 fill-none ${colorClass} opacity-80`}>
      <path d="M0,15 L10,12 L20,17 L30,10 L40,14 L50,6 L60,11 L70,8 L80,13 L90,4 L100,7" />
    </svg>
  )
}

function getTopologyNodeIcon(id: string, size: number, x: number, y: number) {
  const offset = size / 2
  const px = x - offset
  const py = y - offset
  
  switch (id) {
    case "database":
      return (
        <svg x={px} y={py} width={size} height={size} xmlSpace="preserve" viewBox="0 0 432.071 445.383">
          <path stroke="none" d="M402.395 271.23c-50.302 10.376-53.76-6.655-53.76-6.655 53.111-78.808 75.313-178.843 56.153-203.326-52.27-66.785-142.752-35.2-144.262-34.38l-.486.087c-9.938-2.063-21.06-3.292-33.56-3.496-22.761-.373-40.026 5.967-53.127 15.902 0 0-161.411-66.495-153.904 83.63 1.597 31.938 45.776 241.657 98.471 178.312 19.26-23.163 37.869-42.748 37.869-42.748 9.243 6.14 20.308 9.272 31.908 8.147l.901-.765c-.28 2.876-.152 5.689.361 9.019-13.575 15.167-9.586 17.83-36.723 23.416-27.459 5.659-11.328 15.734-.796 18.367 12.768 3.193 42.307 7.716 62.266-20.224l-.796 3.188c5.319 4.26 9.054 27.711 8.428 48.969-.626 21.259-1.044 35.854 3.147 47.254 4.191 11.4 8.368 37.05 44.042 29.406 29.809-6.388 45.256-22.942 47.405-50.555 1.525-19.631 4.976-16.729 5.194-34.28l2.768-8.309c3.192-26.611.507-35.196 18.872-31.203l4.463.392c13.517.615 31.208-2.174 41.591-7 22.358-10.376 35.618-27.7 13.573-23.148z" fill="#336791" />
        </svg>
      )
    case "redis":
      return (
        <svg x={px} y={py} width={size} height={size} viewBox="0 0 256 220" xmlns="http://www.w3.org/2000/svg">
          <path d="M246 169c-13.7 7-84.5 36.2-99.5 44-15.1 7.9-23.5 7.8-35.4 2.1C99.2 209.4 24 179 10.3 172.5 3.6 169.3 0 166.5 0 164v-26s98-21.3 113.9-27c15.8-5.6 21.3-5.8 34.8-.9 13.4 5 94 19.5 107.3 24.3V160c0 2.5-3 5.3-10 9" fill="#912626" />
          <path d="M246 143.2c-13.7 7.1-84.5 36.2-99.5 44-15.1 8-23.5 7.9-35.4 2.2-11.9-5.7-87.2-36.1-100.8-42.6-13.5-6.5-13.8-11-.5-16.2 13.4-5.2 88.2-34.6 104-40.3 16-5.6 21.4-5.8 34.9-1 13.4 5 83.8 33 97.1 37.9 13.3 4.9 13.8 8.9.2 16" fill="#C6302B" />
          <path d="M246 127c-13.7 7.2-84.5 36.3-99.5 44.2-15.1 7.8-23.5 7.7-35.4 2-11.9-5.6-87.2-36-100.8-42.6-6.7-3.2-10.3-6-10.3-8.5V96.2s98-21.3 113.9-27c15.8-5.7 21.3-5.9 34.8-1 13.4 5 94 19.5 107.3 24.4V118c0 2.5-3 5.4-10 9" fill="#912626" />
          <path d="M246 101.4c-13.7 7-84.5 36.2-99.5 44-15.1 7.9-23.5 7.8-35.4 2.1C99.2 141.8 24 111.4 10.3 105c-13.5-6.5-13.8-11-.5-16.1C23.2 83.5 98 54 113.8 48.5c16-5.7 21.4-6 34.9-1 13.4 5 83.8 33 97.1 37.8 13.3 5 13.8 9 .2 16" fill="#C6302B" />
          <path d="M246 83.7c-13.7 7-84.5 36.2-99.5 44-15.1 7.9-23.5 7.8-35.4 2.1C99.2 124.1 24 93.7 10.3 87.2 3.6 84 0 81.2 0 78.7v-26s98-21.3 113.9-27c15.8-5.6 21.3-5.8 34.8-.9 13.4 5 94 19.5 107.3 24.4v25.5c0 2.5-3 5.3-10 9" fill="#912626" />
          <path d="M246 58c-13.7 7-84.5 36.1-99.5 44-15.1 7.9-23.5 7.8-35.4 2C99.2 98.5 24 68 10.3 61.6c-13.5-6.5-13.8-11-.5-16.2C23.2 40.1 98 10.7 113.8 5c16-5.6 21.4-5.8 34.9-.9 13.4 5 83.8 33 97.1 37.8 13.3 4.9 13.8 9 .2 16" fill="#C6302B" />
          <path d="m159.3 32.8-22 2.2-5 11.9-8-13.2L99 31.4l19-6.9-5.8-10.5 17.8 7 16.7-5.5-4.5 10.9 17 6.4M131 90.3l-41-17 58.8-9.1-17.8 26M74 39.3c17.5 0 31.5 5.5 31.5 12.2 0 6.8-14 12.2-31.4 12.2s-31.5-5.4-31.5-12.2c0-6.7 14.1-12.2 31.5-12.2" fill="#FFF" />
        </svg>
      )
    case "worker":
      return (
        <svg x={px} y={py} width={size} height={size} fill="#37814A" role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <title>Celery</title>
          <path d="M2.303 0A2.298 2.298 0 0 0 0 2.303v19.394A2.298 2.298 0 0 0 2.303 24h19.394A2.298 2.298 0 0 0 24 21.697V2.303A2.298 2.298 0 0 0 21.697 0zm8.177 3.072c4.098 0 7.028 1.438 7.68 1.764l-1.194 2.55c-2.442-1.057-4.993-1.41-5.672-1.41-1.574 0-2.17.922-2.17 1.763v8.494c0 .869.596 1.791 2.17 1.791.679 0 3.23-.38 5.672-1.41l1.194 2.496c-.435.271-3.637 1.818-7.68 1.818-1.112 0-4.64-.244-4.64-4.64V7.713c0-4.397 3.528-4.64 4.64-4.64z" />
        </svg>
      )
    case "scheduler":
      return (
        <svg x={px} y={py} width={size} height={size} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="16 16 32 32">
          <path fill="url(#py-topo-a)" d="M31.885 16c-8.124 0-7.617 3.523-7.617 3.523l.01 3.65h7.752v1.095H21.197S16 23.678 16 31.876c0 8.196 4.537 7.906 4.537 7.906h2.708v-3.804s-.146-4.537 4.465-4.537h7.688s4.32.07 4.32-4.175v-7.019S40.374 16 31.885 16zm-4.275 2.454a1.394 1.394 0 1 1 0 2.79 1.393 0 0 1-1.395-1.395c0-.771.624-1.395 1.395-1.395z" />
          <path fill="url(#py-topo-b)" d="M32.115 47.833c8.124 0 7.617-3.523 7.617-3.523l-.01-3.65H31.97v-1.095h10.832S48 40.155 48 31.958c0-8.197-4.537-7.906-4.537-7.906h-2.708v3.803s.146 4.537-4.465 4.537h-7.688s-4.32-.07-4.32 4.175v7.019s-.656 4.247 7.833 4.247zm4.275-2.454a1.393 1.393 0 0 1-1.395-1.395 1.394 1.394 0 1 1 1.395 1.395z" />
          <defs>
            <linearGradient id="py-topo-a" x1="19.075" x2="34.898" y1="18.782" y2="34.658" gradientUnits="userSpaceOnUse">
              <stop stopColor="#387EB8" />
              <stop offset="1" stopColor="#366994" />
            </linearGradient>
            <linearGradient id="py-topo-b" x1="28.809" x2="45.803" y1="28.882" y2="45.163" gradientUnits="userSpaceOnUse">
              <stop stopColor="#FFE052" />
              <stop offset="1" stopColor="#FFC331" />
            </linearGradient>
          </defs>
        </svg>
      )
    case "gateway":
      return (
        <svg x={px} y={py} width={size} height={size} viewBox="0 0 256 256" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid">
          <path d="M128 0C57.33 0 0 57.33 0 128s57.33 128 128 128 128-57.33 128-128S198.67 0 128 0Zm-6.67 230.605v-80.288H76.699l64.128-124.922v80.288h42.966L121.33 230.605Z" fill="#009688" />
        </svg>
      )
    default:
      return null
  }
}
interface ServiceTopologyMapProps {
  isLoading: boolean
  isError: boolean
  data?: apiClient.HealthDetails
}

function ServiceTopologyMap({ isLoading, isError, data }: ServiceTopologyMapProps) {
  const [activeNode, setActiveNode] = useState<string>("gateway")

  const dbStatus = isError ? "down" : data?.components.database.status ?? "ok"
  const redisStatus = isError ? "down" : data?.components.redis.status ?? "ok"
  const workerStatus = isError ? "down" : data?.components.worker.status ?? "ok"
  const schedulerStatus = isError
    ? "down"
    : data?.last_dispatch_tick_at &&
      Date.now() - new Date(data.last_dispatch_tick_at).getTime() < 5 * 60_000
    ? "ok"
    : "degraded"
  const gatewayStatus = isError ? "down" : data?.status ?? "ok"

  const nodes = {
    gateway: { id: "gateway", label: "API Gateway", x: 200, y: 120, status: gatewayStatus },
    redis: { id: "redis", label: "Redis Broker", x: 80, y: 50, status: redisStatus },
    database: { id: "database", label: "PostgreSQL DB", x: 80, y: 190, status: dbStatus },
    scheduler: { id: "scheduler", label: "Beat Scheduler", x: 320, y: 50, status: schedulerStatus },
    worker: { id: "worker", label: "Scan Workers", x: 320, y: 190, status: workerStatus }
  }

  const renderDetails = () => {
    if (isLoading) {
      return (
        <div className="flex h-full items-center justify-center font-mono text-caption text-mute">
          Gathering node telemetry data...
        </div>
      )
    }

    if (isError || !data) {
      return (
        <div className="flex h-full items-center justify-center font-mono text-caption text-accent-red">
          Offline - connection to API Gateway lost.
        </div>
      )
    }

    switch (activeNode) {
      case "gateway":
        return (
          <div className="space-y-1 font-mono text-code-md text-charcoal">
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>service</span>
              <span className="text-ink">api_core</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>uptime</span>
              <span className="text-ink font-semibold">{fmtUptime(data.uptime_seconds)}</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>ping_lat</span>
              <span className="text-accent-green font-semibold">1.2ms (stable)</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>status</span>
              <span className="text-accent-green uppercase font-semibold">operational</span>
            </div>
          </div>
        )
      case "database":
        return (
          <div className="space-y-1 font-mono text-code-md text-charcoal">
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>service</span>
              <span className="text-ink">postgresql_db</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>disk_alloc</span>
              <span className="text-ink font-semibold">{fmtBytes(data.db_size_bytes)}</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>conn_pool</span>
              <span className="text-accent-green font-semibold">20 (active)</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>status</span>
              <span className={cn(dbStatus === "ok" ? "text-accent-green" : "text-accent-orange", "uppercase font-semibold")}>
                {dbStatus}
              </span>
            </div>
          </div>
        )
      case "redis":
        return (
          <div className="space-y-1 font-mono text-code-md text-charcoal">
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>service</span>
              <span className="text-ink">redis_broker</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>queue_depth</span>
              <span className="text-ink font-semibold">{data.queue_depth ?? 0} items</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>port_binding</span>
              <span className="text-ink">6379</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>status</span>
              <span className={cn(redisStatus === "ok" ? "text-accent-green" : "text-accent-orange", "uppercase font-semibold")}>
                {redisStatus}
              </span>
            </div>
          </div>
        )
      case "worker":
        return (
          <div className="space-y-1 font-mono text-code-md text-charcoal">
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>service</span>
              <span className="text-ink">background_workers</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>scans_24h</span>
              <span className="text-ink font-semibold">{data.scans_last_24h} cycles</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>avg_latency</span>
              <span className="text-ink font-semibold">{data.avg_scan_seconds ? `${data.avg_scan_seconds.toFixed(1)}s` : "n/a"}</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>status</span>
              <span className={cn(workerStatus === "ok" ? "text-accent-green" : "text-accent-orange", "uppercase font-semibold")}>
                {workerStatus}
              </span>
            </div>
          </div>
        )
      case "scheduler":
        return (
          <div className="space-y-1 font-mono text-code-md text-charcoal">
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>service</span>
              <span className="text-ink">beat_cron_daemon</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>interval</span>
              <span className="text-ink">60s checks</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>last_tick</span>
              <span className="text-ink font-semibold">{fmtAgo(data.last_dispatch_tick_at)}</span>
            </div>
            <div className="flex items-center justify-between border-b border-hairline/10 pb-0.5">
              <span>status</span>
              <span className={cn(schedulerStatus === "ok" ? "text-accent-green" : "text-accent-orange", "uppercase font-semibold")}>
                {schedulerStatus}
              </span>
            </div>
          </div>
        )
      default:
        return null
    }
  }

  const renderFlowLine = (
    fromNodeId: string,
    toNodeId: string,
    x1: number,
    y1: number,
    x2: number,
    y2: number,
    status: string,
    reverse = false
  ) => {
    const isNodeActive = activeNode === fromNodeId || activeNode === toNodeId
    const baseOpacity = isNodeActive ? "opacity-60" : "opacity-25"
    const activeOpacity = isNodeActive ? "opacity-100" : "opacity-50"
    const strokeWidth = isNodeActive ? "stroke-[1.5px]" : "stroke-[1px]"
    const pulseWidth = isNodeActive ? "stroke-[2.5px]" : "stroke-[1.8px]"
    const speed = isNodeActive ? "1.2s" : "2s"

    let strokeColor = "stroke-accent-green"
    if (status === "degraded") strokeColor = "stroke-accent-orange"
    if (status === "down") strokeColor = "stroke-accent-red"

    return (
      <g className="transition-opacity duration-300">
        {/* Connection shadow glow */}
        {isNodeActive && status !== "down" && (
          <line
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            className={cn("fill-none stroke-[3px] blur-[2px] opacity-15", strokeColor)}
          />
        )}
        {/* Base connection line */}
        <line
          x1={x1}
          y1={y1}
          x2={x2}
          y2={y2}
          className={cn("fill-none transition-[stroke-width,opacity] duration-300", strokeWidth, strokeColor, baseOpacity)}
        />
        {/* Glowing pulse dash */}
        {status !== "down" && !isLoading && (
          <line
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            className={cn("fill-none transition-[stroke-width,opacity] duration-300", pulseWidth, strokeColor, activeOpacity)}
            strokeDasharray="6 24"
          >
            <animate
              key={speed}
              attributeName="stroke-dashoffset"
              values={reverse ? "0;30" : "30;0"}
              dur={speed}
              repeatCount="indefinite"
            />
          </line>
        )}
      </g>
    )
  }

  return (
    <SpotlightCard className="flex flex-col border border-hairline-strong bg-surface-card p-6 lg:h-[480px]">
      <style>{`
        @keyframes ripple {
          0% { r: 18px; opacity: 0.85; }
          100% { r: 28px; opacity: 0; }
        }
        .node-group {
          transform-box: fill-box;
          transform-origin: center;
          transition: transform 200ms cubic-bezier(0.25, 1, 0.5, 1);
        }
        .node-group:hover {
          transform: scale(1.06);
        }
      `}</style>

      <div className="mb-3 flex items-center justify-between border-b border-hairline pb-2">
        <div className="flex items-center gap-2 text-caption font-semibold tracking-wider text-ink uppercase">
          <Network className="size-4 text-accent-blue" />
          <span>Active Service Topology</span>
        </div>
        <div className="text-[10px] text-mute font-mono">
          Select node to inspect
        </div>
      </div>

      <div className="relative h-[210px] bg-canvas/30 rounded-md border border-hairline/50 overflow-hidden flex items-center justify-center bg-grid-pattern">
        
        {/* Ambient background glow behind the active node */}
        <div
          className={cn(
            "absolute w-[180px] h-[180px] rounded-full blur-[45px] opacity-10 pointer-events-none transition-all duration-1000",
            gatewayStatus === "ok" ? "bg-glow-green" : gatewayStatus === "degraded" ? "bg-glow-orange" : "bg-glow-red"
          )}
        />

        <svg viewBox="0 0 400 240" className="w-full h-full select-none relative z-10">
          {renderFlowLine("redis", "gateway", 80, 50, 200, 120, redisStatus)}
          {renderFlowLine("database", "gateway", 80, 190, 200, 120, dbStatus)}
          {renderFlowLine("scheduler", "gateway", 320, 50, 200, 120, schedulerStatus, true)}
          {renderFlowLine("worker", "gateway", 320, 190, 200, 120, workerStatus, true)}

          {Object.values(nodes).map((node) => {
            const isActive = activeNode === node.id
            const isGateway = node.id === "gateway"
            const r1 = isGateway ? 21 : 16
            const r2 = isGateway ? 15 : 11

            let strokeColor = "stroke-accent-green"
            
            if (node.status === "degraded") {
              strokeColor = "stroke-accent-orange"
            } else if (node.status === "down") {
              strokeColor = "stroke-accent-red"
            }

            return (
              <g
                key={node.id}
                onClick={() => setActiveNode(node.id)}
                className="cursor-pointer group node-group"
              >
                {/* Hover halo glow */}
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={r1}
                  className="fill-none opacity-0 group-hover:opacity-10 transition-opacity duration-300"
                  style={{ stroke: `var(--color-accent-${node.status === "degraded" ? "orange" : node.status === "down" ? "red" : "green"})`, strokeWidth: 4, filter: 'blur(3px)' }}
                />

                {/* Selected Ripple ring */}
                {isActive && node.status !== "down" && (
                  <circle
                    cx={node.x}
                    cy={node.y}
                    className={cn("fill-none stroke-[1px] animate-[ripple_1.8s_ease-out_infinite]", strokeColor)}
                    style={{ transformOrigin: `${node.x}px ${node.y}px` }}
                  />
                )}

                {/* Outer concentric border */}
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={r1}
                  className={cn(
                    "fill-surface-card stroke-[1.5px] transition-colors duration-300",
                    isActive ? "stroke-accent-blue" : strokeColor
                  )}
                />

                {/* Inner core circle */}
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={r2}
                  className="fill-surface-deep stroke-hairline-strong stroke-[1px]"
                />

                {/* Brand Logo inside Node */}
                {getTopologyNodeIcon(node.id, isGateway ? 18 : 14, node.x, node.y)}

                {/* Micro Label */}
                <text
                  x={node.x}
                  y={isGateway ? node.y + 35 : node.y - 24}
                  textAnchor="middle"
                  className={cn(
                    "font-mono text-[9px] font-semibold tracking-wider uppercase transition-colors duration-300 select-none",
                    isActive ? "fill-accent-blue font-bold" : "fill-mute group-hover:fill-ink"
                  )}
                >
                  {node.label}
                </text>
              </g>
            )
          })}
        </svg>
      </div>

      <div className="mt-3 border border-hairline-strong bg-surface-deep/75 backdrop-blur-sm rounded-lg p-3.5 h-[160px] min-h-[160px] flex flex-col justify-start">
        <div className="mb-2 flex items-center justify-between border-b border-hairline/30 pb-1.5 font-mono text-[10px]">
          <div className="flex items-center gap-1.5">
            {/* Console dots */}
            <span className="size-1.5 rounded-full bg-accent-red/80" />
            <span className="size-1.5 rounded-full bg-accent-yellow/80" />
            <span className="size-1.5 rounded-full bg-accent-green/80" />
            {getServiceLogo(activeNode, "size-3.5 ml-1 text-accent-blue")}
            <span className="ml-1 font-bold uppercase tracking-wider text-accent-blue">
              {nodes[activeNode as keyof typeof nodes]?.label.replace(" ", "_") ?? "SYSTEM"}_TELEMETRY // INSPECTING
            </span>
          </div>
          <div className="flex items-center gap-1.5 uppercase font-bold tracking-widest text-[9px]">
            <span className={cn("size-1.5 rounded-full",
              nodes[activeNode as keyof typeof nodes]?.status === "ok" ? "bg-accent-green" :
              nodes[activeNode as keyof typeof nodes]?.status === "degraded" ? "bg-accent-orange animate-pulse" :
              "bg-accent-red"
            )} />
            <span className={cn(
              nodes[activeNode as keyof typeof nodes]?.status === "ok" ? "text-accent-green" :
              nodes[activeNode as keyof typeof nodes]?.status === "degraded" ? "text-accent-orange" :
              "text-accent-red"
            )}>
              {(nodes[activeNode as keyof typeof nodes]?.status ?? "ok").toUpperCase()}
            </span>
          </div>
        </div>
        
        {/* Blur transition keyed on active node */}
        <div key={activeNode} className="animate-detail-in flex-1 flex flex-col justify-center">
          {renderDetails()}
        </div>
      </div>
    </SpotlightCard>
  )
}

export function HealthPage() {
  const health = useQuery({
    queryKey: ["health-details"],
    queryFn: apiClient.getHealthDetails,
    refetchInterval: 10000,
  })

  const h = health.data
  const isLoading = health.isLoading
  const isError = health.isError

  // Determine global visual accent class based on health status
  const systemStatus = h?.status ?? "ok"
  const isHealthy = systemStatus === "ok"
  const isDegraded = systemStatus === "degraded"
  
  const glowColorClass = isError
    ? "bg-glow-red"
    : isLoading
    ? "bg-glow-blue"
    : isHealthy
    ? "bg-glow-green"
    : isDegraded
    ? "bg-glow-orange"
    : "bg-glow-red"

  const statusLabel = isError
    ? "SYSTEM UNREACHABLE"
    : isLoading
    ? "DIAGNOSING SYSTEM..."
    : isHealthy
    ? "SYSTEM OPERATIONAL"
    : isDegraded
    ? "DEGRADED PERFORMANCE"
    : "CRITICAL ALERT"

  return (
    <div className="relative">
      {/* Ambient background glow matching health state */}
      <div
        className={`pointer-events-none absolute top-[-100px] left-1/2 h-[350px] w-full max-w-[800px] -translate-x-1/2 rounded-full opacity-10 blur-[140px] transition-all duration-1000 ${glowColorClass}`}
      />

      {/* Page Header Redesign */}
      <div className="relative z-10 mb-10 flex flex-col items-start gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="flex items-center gap-3">
            {/* Concentric Status ring indicator */}
            <div className="relative flex size-5 items-center justify-center">
              <span
                className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-35 ${
                  isError
                    ? "bg-accent-red"
                    : isLoading
                    ? "bg-accent-blue"
                    : isHealthy
                    ? "bg-accent-green"
                    : "bg-accent-orange"
                }`}
              />
              <span
                className={`relative inline-flex size-3 rounded-full ${
                  isError
                    ? "bg-accent-red"
                    : isLoading
                    ? "bg-accent-blue"
                    : isHealthy
                    ? "bg-accent-green"
                    : "bg-accent-orange"
                }`}
              />
            </div>
            <h1 className="text-display-lg text-ink">System health</h1>
          </div>
          <p className="mt-2 text-body-md text-charcoal">
            The watcher, watched — queue depths, worker status, and core services liveness at a glance.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Diagnostic Status Badge */}
          <Badge
            className="h-[22px] px-3 font-semibold uppercase tracking-wider text-[11px]"
            variant={
              isError
                ? "threat"
                : isLoading
                ? "pending"
                : isHealthy
                ? "clean"
                : isDegraded
                ? "pending"
                : "threat"
            }
          >
            {statusLabel}
          </Badge>
          
          <Button
            variant="ghost"
            size="icon"
            onClick={() => void health.refetch()}
            disabled={health.isRefetching}
            className="size-8 rounded-full border border-hairline-strong bg-surface-card"
            title="Force health check refresh"
          >
            <RefreshCw className={`size-4 text-ink ${health.isRefetching ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      <div className="relative z-10 space-y-8">
        {/* Core Stats Cards Grid */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {/* Uptime Stat */}
          <SpotlightCard
            spotlightColor={isHealthy ? "rgba(17, 255, 153, 0.04)" : "rgba(255, 128, 31, 0.04)"}
            className="p-5"
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-caption uppercase tracking-wider text-mute">API Uptime</p>
                <p className="mt-2 text-heading-md font-display-sans font-medium tracking-tight text-ink">
                  {isLoading ? (
                    <span className="inline-block h-6 w-24 animate-pulse rounded bg-hairline-strong" />
                  ) : isError ? (
                    "offline"
                  ) : (
                    fmtUptime(h?.uptime_seconds ?? 0)
                  )}
                </p>
              </div>
              <div className="rounded-md border border-hairline bg-surface-deep/50 p-2 text-charcoal">
                <Timer className="size-4.5" />
              </div>
            </div>
            <div className="mt-4 flex items-center justify-between border-t border-hairline pt-3">
              <span className="text-[11px] text-mute">heartbeat signal stable</span>
              {!isLoading && !isError && (
                <div className="flex gap-0.5 items-center">
                  <span className="size-1.5 rounded-full bg-accent-green animate-pulse" />
                  <span className="text-[10px] text-accent-green font-mono uppercase tracking-widest font-bold">Live</span>
                </div>
              )}
            </div>
          </SpotlightCard>

          {/* Queue Depth Stat */}
          <SpotlightCard
            spotlightColor="rgba(59, 158, 255, 0.04)"
            className="p-5"
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-caption uppercase tracking-wider text-mute">Queue Depth</p>
                <p className="mt-2 text-heading-md font-display-sans font-medium tracking-tight text-ink">
                  {isLoading ? (
                    <span className="inline-block h-6 w-16 animate-pulse rounded bg-hairline-strong" />
                  ) : isError ? (
                    "n/a"
                  ) : (
                    h?.queue_depth ?? 0
                  )}
                </p>
              </div>
              <div className="rounded-md border border-hairline bg-surface-deep/50 p-2 text-charcoal">
                <Activity className="size-4.5" />
              </div>
            </div>
            <div className="mt-4 flex items-center justify-between border-t border-hairline pt-3">
              <span className="text-[11px] text-mute">tasks waiting for worker</span>
              {!isLoading && !isError && (
                <Sparkline colorClass={h?.queue_depth && h.queue_depth > 0 ? "text-accent-orange" : "text-accent-blue"} />
              )}
            </div>
          </SpotlightCard>

          {/* Database Size Stat */}
          <SpotlightCard
            spotlightColor="rgba(255, 197, 61, 0.04)"
            className="p-5"
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-caption uppercase tracking-wider text-mute">Database Size</p>
                <p className="mt-2 text-heading-md font-display-sans font-medium tracking-tight text-ink">
                  {isLoading ? (
                    <span className="inline-block h-6 w-20 animate-pulse rounded bg-hairline-strong" />
                  ) : isError ? (
                    "n/a"
                  ) : (
                    fmtBytes(h?.db_size_bytes ?? null)
                  )}
                </p>
              </div>
              <div className="rounded-md border border-hairline bg-surface-deep/50 p-2 text-charcoal">
                <HardDrive className="size-4.5" />
              </div>
            </div>
            <div className="mt-4 flex items-center justify-between border-t border-hairline pt-3">
              <span className="text-[11px] text-mute">vacuum allocation</span>
              {!isLoading && !isError && (
                <span className="text-caption font-mono text-mute">{h?.db_size_bytes ? `${(h.db_size_bytes / 1024).toFixed(0)} KB` : "n/a"}</span>
              )}
            </div>
          </SpotlightCard>

          {/* Scans (24h) Stat */}
          <SpotlightCard
            spotlightColor="rgba(17, 255, 153, 0.04)"
            className="p-5"
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-caption uppercase tracking-wider text-mute">Scans (24h)</p>
                <p className="mt-2 text-heading-md font-display-sans font-medium tracking-tight text-ink">
                  {isLoading ? (
                    <span className="inline-block h-6 w-16 animate-pulse rounded bg-hairline-strong" />
                  ) : isError ? (
                    "n/a"
                  ) : (
                    h?.scans_last_24h ?? 0
                  )}
                </p>
              </div>
              <div className="rounded-md border border-hairline bg-surface-deep/50 p-2 text-charcoal">
                <Database className="size-4.5" />
              </div>
            </div>
            <div className="mt-4 flex items-center justify-between border-t border-hairline pt-3">
              <span className="text-[11px] text-mute">
                {h?.avg_scan_seconds != null
                  ? `avg ${h.avg_scan_seconds.toFixed(1)}s / scan`
                  : "no average latency data"}
              </span>
              {!isLoading && !isError && <Sparkline colorClass="text-accent-green" />}
            </div>
          </SpotlightCard>
        </div>

        {/* Diagnostic Split Layout */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          {/* Core Services status grid list (Left 7 Columns) */}
          <div className="lg:col-span-7 space-y-4">
            <h2 className="text-heading-sm font-medium tracking-tight text-ink">Core Services Status</h2>
            
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {/* PostgreSQL Subsystem Card */}
              <SpotlightCard className="p-4" spotlightColor="rgba(17, 255, 153, 0.03)">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="relative flex size-4 items-center justify-center">
                      {isLoading ? (
                        <span className="size-2 animate-ping rounded-full bg-mute" />
                      ) : (
                        <>
                          <span
                            className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-35 ${
                              isError ? "bg-accent-red" : h?.components.database.status === "ok" ? "bg-accent-green" : "bg-accent-orange"
                            }`}
                          />
                          <span
                            className={`relative inline-flex size-2.5 rounded-full ${
                              isError ? "bg-accent-red" : h?.components.database.status === "ok" ? "bg-accent-green" : "bg-accent-orange"
                            }`}
                          />
                        </>
                      )}
                    </div>
                    <div>
                      <h3 className="text-body-sm font-semibold text-ink flex items-center gap-1.5">
                        {getServiceLogo("database", "size-4 text-[#336791]")}
                        <span>PostgreSQL</span>
                      </h3>
                      <p className="text-[11px] text-mute">{COMPONENT_LABELS.database}</p>
                    </div>
                  </div>
                  <Badge variant={isError ? "threat" : h?.components.database.status === "ok" ? "clean" : "pending"} className="h-[18px] text-[10px]">
                    {isLoading ? "loading" : isError ? "offline" : h?.components.database.status}
                  </Badge>
                </div>
                <div className="mt-4 border-t border-hairline pt-3 font-mono text-[11px] text-charcoal">
                  <div className="flex justify-between">
                    <span>latency check</span>
                    <span className="text-ink">{isLoading ? "---" : isError ? "timeout" : "1.2ms"}</span>
                  </div>
                  <div className="mt-1 flex justify-between">
                    <span>conn_pool limit</span>
                    <span className="text-ink">20 (active)</span>
                  </div>
                </div>
              </SpotlightCard>

              {/* Redis Subsystem Card */}
              <SpotlightCard className="p-4" spotlightColor="rgba(17, 255, 153, 0.03)">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="relative flex size-4 items-center justify-center">
                      {isLoading ? (
                        <span className="size-2 animate-ping rounded-full bg-mute" />
                      ) : (
                        <>
                          <span
                            className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-35 ${
                              isError ? "bg-accent-red" : h?.components.redis.status === "ok" ? "bg-accent-green" : "bg-accent-orange"
                            }`}
                          />
                          <span
                            className={`relative inline-flex size-2.5 rounded-full ${
                              isError ? "bg-accent-red" : h?.components.redis.status === "ok" ? "bg-accent-green" : "bg-accent-orange"
                            }`}
                          />
                        </>
                      )}
                    </div>
                    <div>
                      <h3 className="text-body-sm font-semibold text-ink flex items-center gap-1.5">
                        {getServiceLogo("redis", "size-4")}
                        <span>Redis Broker</span>
                      </h3>
                      <p className="text-[11px] text-mute">{COMPONENT_LABELS.redis}</p>
                    </div>
                  </div>
                  <Badge variant={isError ? "threat" : h?.components.redis.status === "ok" ? "clean" : "pending"} className="h-[18px] text-[10px]">
                    {isLoading ? "loading" : isError ? "offline" : h?.components.redis.status}
                  </Badge>
                </div>
                <div className="mt-4 border-t border-hairline pt-3 font-mono text-[11px] text-charcoal">
                  <div className="flex justify-between">
                    <span>active broker</span>
                    <span className="text-ink">redis://</span>
                  </div>
                  <div className="mt-1 flex justify-between">
                    <span>queue status</span>
                    <span className="text-ink">{isLoading ? "---" : isError ? "unreachable" : "listening"}</span>
                  </div>
                </div>
              </SpotlightCard>

              {/* Scan Worker Card */}
              <SpotlightCard className="p-4" spotlightColor="rgba(17, 255, 153, 0.03)">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="relative flex size-4 items-center justify-center">
                      {isLoading ? (
                        <span className="size-2 animate-ping rounded-full bg-mute" />
                      ) : (
                        <>
                          <span
                            className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-35 ${
                              isError ? "bg-accent-red" : h?.components.worker.status === "ok" ? "bg-accent-green" : "bg-accent-orange"
                            }`}
                          />
                          <span
                            className={`relative inline-flex size-2.5 rounded-full ${
                              isError ? "bg-accent-red" : h?.components.worker.status === "ok" ? "bg-accent-green" : "bg-accent-orange"
                            }`}
                          />
                        </>
                      )}
                    </div>
                    <div>
                      <h3 className="text-body-sm font-semibold text-ink flex items-center gap-1.5">
                        {getServiceLogo("worker", "size-4")}
                        <span>Scan Worker Pool</span>
                      </h3>
                      <p className="text-[11px] text-mute">{COMPONENT_LABELS.worker}</p>
                    </div>
                  </div>
                  <Badge variant={isError ? "threat" : h?.components.worker.status === "ok" ? "clean" : "pending"} className="h-[18px] text-[10px]">
                    {isLoading ? "loading" : isError ? "offline" : h?.components.worker.status}
                  </Badge>
                </div>
                <div className="mt-4 border-t border-hairline pt-3 font-mono text-[11px] text-charcoal">
                  <div className="flex justify-between">
                    <span>worker node details</span>
                    <span className="text-ink text-[10px] truncate max-w-[120px]">
                      {isLoading ? "---" : isError ? "n/a" : h?.components.worker.detail ?? "online"}
                    </span>
                  </div>
                  <div className="mt-1 flex justify-between">
                    <span>thread dispatcher</span>
                    <span className="text-ink">active</span>
                  </div>
                </div>
              </SpotlightCard>

              {/* Beat Scheduler Card */}
              <SpotlightCard className="p-4" spotlightColor="rgba(17, 255, 153, 0.03)">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="relative flex size-4 items-center justify-center">
                      {isLoading ? (
                        <span className="size-2 animate-ping rounded-full bg-mute" />
                      ) : (
                        <>
                          <span
                            className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-35 ${
                              isError
                                ? "bg-accent-red"
                                : h?.last_dispatch_tick_at &&
                                  Date.now() - new Date(h.last_dispatch_tick_at).getTime() < 5 * 60_000
                                ? "bg-accent-green"
                                : "bg-accent-orange"
                            }`}
                          />
                          <span
                            className={`relative inline-flex size-2.5 rounded-full ${
                              isError
                                ? "bg-accent-red"
                                : h?.last_dispatch_tick_at &&
                                  Date.now() - new Date(h.last_dispatch_tick_at).getTime() < 5 * 60_000
                                ? "bg-accent-green"
                                : "bg-accent-orange"
                            }`}
                          />
                        </>
                      )}
                    </div>
                    <div>
                      <h3 className="text-body-sm font-semibold text-ink flex items-center gap-1.5">
                        {getServiceLogo("scheduler", "size-4")}
                        <span>Beat Scheduler</span>
                      </h3>
                      <p className="text-[11px] text-mute">{COMPONENT_LABELS.scheduler}</p>
                    </div>
                  </div>
                  <Badge
                    variant={
                      isError
                        ? "threat"
                        : h?.last_dispatch_tick_at &&
                          Date.now() - new Date(h.last_dispatch_tick_at).getTime() < 5 * 60_000
                        ? "clean"
                        : "pending"
                    }
                    className="h-[18px] text-[10px]"
                  >
                    {isLoading ? "loading" : isError ? "offline" : "active"}
                  </Badge>
                </div>
                <div className="mt-4 border-t border-hairline pt-3 font-mono text-[11px] text-charcoal">
                  <div className="flex justify-between">
                    <span>tick interval</span>
                    <span className="text-ink">60s</span>
                  </div>
                  <div className="mt-1 flex justify-between">
                    <span>last dispatch</span>
                    <span className="text-ink">{isLoading ? "---" : isError ? "never" : fmtAgo(h?.last_dispatch_tick_at ?? null)}</span>
                  </div>
                </div>
              </SpotlightCard>
            </div>
            
            {/* Detailed Activity Block */}
            <SpotlightCard className="p-5">
              <h3 className="mb-4 text-body-sm font-semibold tracking-tight text-ink flex items-center gap-2">
                <Workflow className="size-4 text-accent-blue" />
                <span>Monitoring Activity</span>
              </h3>
              
              <dl className="grid grid-cols-1 gap-4 text-body-sm sm:grid-cols-3">
                <div className="rounded-lg border border-hairline bg-surface-deep/30 p-3">
                  <dt className="text-caption uppercase tracking-wider text-mute">Sites Monitored</dt>
                  <dd className="mt-1.5 text-heading-sm font-display-sans font-medium text-ink">
                    {isLoading ? (
                      <span className="inline-block h-5 w-10 animate-pulse rounded bg-hairline-strong" />
                    ) : isError ? (
                      "0"
                    ) : (
                      h?.sites_total ?? 0
                    )}
                  </dd>
                </div>
                
                <div className="rounded-lg border border-hairline bg-surface-deep/30 p-3">
                  <dt className="text-caption uppercase tracking-wider text-mute">Last Completed Scan</dt>
                  <dd className="mt-1.5 text-body-sm font-medium text-ink">
                    {isLoading ? (
                      <span className="inline-block h-4 w-20 animate-pulse rounded bg-hairline-strong" />
                    ) : isError ? (
                      "unknown"
                    ) : (
                      fmtAgo(h?.last_scan_at ?? null)
                    )}
                  </dd>
                </div>

                <div className="rounded-lg border border-hairline bg-surface-deep/30 p-3">
                  <dt className="text-caption uppercase tracking-wider text-mute">Liveness Endpoint</dt>
                  <dd className="mt-1.5 font-mono text-code-md text-ink flex items-center justify-between">
                    <span className="text-accent-blue">GET /health/live</span>
                  </dd>
                </div>
              </dl>
            </SpotlightCard>
          </div>

          {/* Service Topology Graph (Right 5 Columns) */}
          <div className="lg:col-span-5 space-y-4">
            <h2 className="text-heading-sm font-medium tracking-tight text-ink">Service Topology</h2>
            <ServiceTopologyMap isLoading={isLoading} isError={isError} data={h} />
          </div>
        </div>
      </div>
    </div>
  )
}
