import { useEffect, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Plus,
  Send,
  Server,
  Trash2,
} from "lucide-react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"

import { ApiKeysCard } from "@/components/api-keys-card"
import { StatusDot, type DotState } from "@/components/status-dot"
import { UsersCard } from "@/components/users-card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { CustomSelect } from "@/components/ui/select"
import * as apiClient from "@/lib/api"
import { ApiError, type ChannelType } from "@/lib/api"
import { useAuth } from "@/lib/auth"

/*
 * Settings — notification channels + integrations (§8). Layout follows
 * DESIGN-resend.md: stacked cards on the true-black canvas, hairline
 * borders, one primary action per card at most, accents as text washes.
 */

// --- Custom Select & Icons Component ---

function getChannelIcon(key: string, className?: string) {
  const classStr = cn("size-4.5 shrink-0", className)
  switch (key) {
    case "ntfy":
      return (
        <svg className={classStr} fill="#317F6F" role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <title>ntfy</title>
          <path d="M12.597 13.693v2.156h6.205v-2.156ZM5.183 6.549v2.363l3.591 1.901.023.01-.023.009-3.591 1.901v2.35l.386-.211 5.456-2.969V9.729ZM3.659 2.037C1.915 2.037.42 3.41.42 5.154v.002L.438 18.73 0 21.963l5.956-1.583h14.806c1.744 0 3.238-1.374 3.238-3.118V5.154c0-1.744-1.493-3.116-3.237-3.117h-.001zm0 2.2h17.104c.613.001 1.037.447 1.037.917v12.108c0 .47-.424.916-1.038.916H5.633l-3.026.915.031-.179-.017-13.76c0-.47.424-.917 1.038-.917z" />
        </svg>
      )
    case "slack":
      return (
        <svg className={classStr} viewBox="0 0 2447.6 2452.5" xmlns="http://www.w3.org/2000/svg">
          <g clipRule="evenodd" fillRule="evenodd">
            <path d="m897.4 0c-135.3.1-244.8 109.9-244.7 245.2-.1 135.3 109.5 245.1 244.8 245.2h244.8v-245.1c.1-135.3-109.5-245.1-244.9-245.3.1 0 .1 0 0 0m0 654h-652.6c-135.3.1-244.9 109.9-244.8 245.2-.2 135.3 109.4 245.1 244.7 245.3h652.7c135.3-.1 244.9-109.9 244.8-245.2.1-135.4-109.5-245.2-244.8-245.3z" fill="#36c5f0" />
            <path d="m2447.6 899.2c.1-135.3-109.5-245.1-244.8-245.2-135.3.1-244.9 109.9-244.8 245.2v245.3h244.8c135.3-.1 244.9-109.9 244.8-245.3zm-652.7 0v-654c.1-135.2-109.4-245-244.7-245.2-135.3.1-244.9 109.9-244.8 245.2v654c-.2 135.3 109.4 245.1 244.7 245.3 135.3-.1 244.9-109.9 244.8-245.3z" fill="#2eb67d" />
            <path d="m1550.1 2452.5c135.3-.1 244.9-109.9 244.8-245.2.1-135.3-109.5-245.1-244.8-245.2h-244.8v245.2c-.1 135.2 109.5 245 244.8 245.2zm0-654.1h652.7c135.3-.1 244.9-109.9 244.8-245.2.2-135.3-109.4-245.1-244.7-245.3h-652.7c-135.3.1-244.9 109.9-244.8 245.2-.1 135.4 109.4 245.2 244.7 245.3z" fill="#ecb22e" />
            <path d="m0 1553.2c-.1 135.3 109.5 245.1 244.8 245.2 135.3-.1 244.9-109.9 244.8-245.2v-245.2h-244.8c-135.3.1-244.9 109.9-244.8 245.2zm652.7 0v654c-.2 135.3 109.4 245.1 244.7 245.3 135.3-.1 244.9-109.9 244.8-245.2v-653.9c.2-135.3-109.4-245.1-244.7-245.3-135.4 0-244.9 109.8-244.8 245.1 0 0 0 .1 0 0" fill="#e01e5a" />
          </g>
        </svg>
      )
    case "discord":
      return (
        <svg className={classStr} viewBox="0 0 256 199" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid">
          <path d="M216.856 16.597A208.502 208.502 0 0 0 164.042 0c-2.275 4.113-4.933 9.645-6.766 14.046-19.692-2.961-39.203-2.961-58.533 0-1.832-4.4-4.55-9.933-6.846-14.046a207.809 207.809 0 0 0-52.855 16.638C5.618 67.147-3.443 116.4 1.087 164.956c22.169 16.555 43.653 26.612 64.775 33.193A161.094 161.094 0 0 0 79.735 175.3a136.413 136.413 0 0 1-21.846-10.632 108.636 108.636 0 0 0 5.356-4.237c42.122 19.702 87.89 19.702 129.51 0a131.66 131.66 0 0 0 5.355 4.237 136.07 136.07 0 0 1-21.886 10.653c4.006 8.02 8.638 15.67 13.873 22.848 21.142-6.58 42.646-16.637 64.815-33.213 5.316-56.288-9.08-105.09-38.056-148.36ZM85.474 135.095c-12.645 0-23.015-11.805-23.015-26.18s10.149-26.2 23.015-26.2c12.867 0 23.236 11.804 23.015 26.2.02 14.375-10.148 26.18-23.015 26.18Zm85.051 0c-12.645 0-23.014-11.805-23.014-26.18s10.148-26.2 23.014-26.2c12.867 0 23.236 11.804 23.015 26.2 0 14.375-10.148 26.18-23.015 26.18Z" fill="#5865F2" />
        </svg>
      )
    case "webhook":
      return (
        <svg className={classStr} xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid" viewBox="0 0 256 239" id="webhooks">
          <path fill="#C73A63" d="M119.54 100.503c-10.61 17.836-20.775 35.108-31.152 52.25-2.665 4.401-3.984 7.986-1.855 13.58 5.878 15.454-2.414 30.493-17.998 34.575-14.697 3.851-29.016-5.808-31.932-21.543-2.584-13.927 8.224-27.58 23.58-29.757 1.286-.184 2.6-.205 4.762-.367l23.358-39.168C73.612 95.465 64.868 78.39 66.803 57.23c1.368-14.957 7.25-27.883 18-38.477 20.59-20.288 52.002-23.573 76.246-8.001 23.284 14.958 33.948 44.094 24.858 69.031-6.854-1.858-13.756-3.732-21.343-5.79 2.854-13.865.743-26.315-8.608-36.981-6.178-7.042-14.106-10.733-23.12-12.093-18.072-2.73 35.815 8.88-41.08 26.618-5.976 20.13 3.069 36.575 27.784 48.967z" />
          <path fill="#4B4B4B" d="M149.841 79.41c7.475 13.187 15.065 26.573 22.587 39.836 38.02-11.763 66.686 9.284 76.97 31.817 12.422 27.219 3.93 59.457-20.465 76.25-25.04 17.238-56.707 14.293-78.892-7.851 5.654-4.733 11.336-9.487 17.407-14.566 21.912 14.192 41.077 13.524 55.305-3.282 12.133-14.337 11.87-35.714-.615-49.75-14.408-16.197-33.707-16.691-57.035-1.143-9.677-17.168-19.522-34.199-28.893-51.491-3.16-5.828-6.648-9.21-13.77-10.443-11.893-2.062-19.571-12.275-20.032-23.717-.453-11.316 6.214-21.545 16.634-25.53 10.322-3.949 22.435-.762 29.378 8.014 5.674 7.17 7.477 15.24 4.491 24.083-.83 2.466-1.905 4.852-3.07 7.774z" />
          <path fill="#4A4A4A" d="M167.707 187.21h-45.77c-4.387 18.044-13.863 32.612-30.19 41.876-12.693 7.2-26.373 9.641-40.933 7.29-26.808-4.323-48.728-28.456-50.658-55.63-2.184-30.784 18.975-58.147 47.178-64.293 1.947 7.071 3.915 14.21 5.862 21.264-25.876 13.202-34.832 29.836-27.59 50.636 6.375 18.304 24.484 28.337 44.147 24.457 20.08-3.962 30.204-20.65 28.968-47.432 19.036 0 38.088-.197 57.126.097 7.434.117 13.173-.654 18.773-7.208 9.22-10.784 26.191-9.811 36.121.374 10.148 10.409 9.662 27.157-1.077 37.127-10.361 9.62-26.73 9.106-36.424-1.26-1.992-2.136-3.562-4.673-5.533-7.298z" />
        </svg>
      )
    case "email":
      return (
        <svg className={classStr} xmlns="http://www.w3.org/2000/svg" viewBox="0 49.4 512 399.42">
          <g fill="none" fillRule="evenodd">
            <g fillRule="nonzero">
              <path fill="#4285f4" d="M34.91 448.818h81.454V251L0 163.727V413.91c0 19.287 15.622 34.91 34.91 34.91z" />
              <path fill="#34a853" d="M395.636 448.818h81.455c19.287 0 34.909-15.622 34.909-34.909V163.727L395.636 251z" />
              <path fill="#fbbc04" d="M395.636 99.727V251L512 163.727v-46.545c0-43.142-49.25-67.782-83.782-41.891z" />
            </g>
            <path fill="#ea4335" d="M116.364 251V99.727L256 204.455 395.636 99.727V251L256 355.727z" />
            <path fill="#c5221f" fillRule="nonzero" d="M0 117.182v46.545L116.364 251V99.727L83.782 75.291C49.25 49.4 0 74.04 0 117.18z" />
          </g>
        </svg>
      )
    case "telegram":
      return (
        <svg className={classStr} viewBox="0 0 256 256" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid">
          <defs>
            <linearGradient id="tg-a" x1="50%" x2="50%" y1="0%" y2="100%">
              <stop offset="0%" stopColor="#2AABEE" />
              <stop offset="100%" stopColor="#229ED9" />
            </linearGradient>
          </defs>
          <path fill="url(#tg-a)" d="M128 0C94.06 0 61.48 13.494 37.5 37.49A128.038 128.038 0 0 0 0 128c0 33.934 13.5 66.514 37.5 90.51C61.48 242.506 94.06 256 128 256s66.52-13.494 90.5-37.49c24-23.996 37.5-56.576 37.5-90.51 0-33.934-13.5-66.514-37.5-90.51C194.52 13.494 161.94 0 128 0Z" />
          <path fill="#FFF" d="M57.94 126.648c37.32-16.256 62.2-26.974 74.64-32.152 35.56-14.786 42.94-17.354 47.76-17.441 1.06-.017 3.42.245 4.96 1.49 1.28 1.05 1.64 2.47 1.82 3.467.16.996.38 3.266.2 5.038-1.92 20.24-10.26 69.356-14.5 92.026-1.78 9.592-5.32 12.808-8.74 13.122-7.44.684-13.08-4.912-20.28-9.63-11.26-7.386-17.62-11.982-28.56-19.188-12.64-8.328-4.44-12.906 2.76-20.386 1.88-1.958 34.64-31.748 35.26-34.45.08-.338.16-1.598-.6-2.262-.74-.666-1.84-.438-2.64-.258-1.14.256-19.12 12.152-54 35.686-5.1 3.508-9.72 5.218-13.88 5.128-4.56-.098-13.36-2.584-19.9-4.708-8-2.606-14.38-3.984-13.82-8.41.28-2.304 3.46-4.662 9.52-7.072Z" />
          </svg>
        )
      case "gemini":
        return (
          <svg className={classStr} viewBox="0 0 296 298" xmlns="http://www.w3.org/2000/svg" fill="none">
            <mask id="a" width="296" height="298" x="0" y="0" maskUnits="userSpaceOnUse" style={{ maskType: "alpha" }}>
              <path fill="#3186FF" d="M141.201 4.886c2.282-6.17 11.042-6.071 13.184.148l5.985 17.37a184.004 184.004 0 0 0 111.257 113.049l19.304 6.997c6.143 2.227 6.156 10.91.02 13.155l-19.35 7.082a184.001 184.001 0 0 0-109.495 109.385l-7.573 20.629c-2.241 6.105-10.869 6.121-13.133.025l-7.908-21.296a184 184 0 0 0-109.02-108.658l-19.698-7.239c-6.102-2.243-6.118-10.867-.025-13.132l20.083-7.467A183.998 183.998 0 0 0 133.291 26.28l7.91-21.394Z" />
            </mask>
            <g mask="url(#a)">
              <g filter="url(#b)">
                <ellipse cx="163" cy="149" fill="#3689FF" rx="196" ry="159" />
              </g>
              <g filter="url(#c)">
                <ellipse cx="33.5" cy="142.5" fill="#F6C013" rx="68.5" ry="72.5" />
              </g>
              <g filter="url(#d)">
                <ellipse cx="19.5" cy="148.5" fill="#F6C013" rx="68.5" ry="72.5" />
              </g>
              <g filter="url(#e)">
                <path fill="#FA4340" d="M194 10.5C172 82.5 65.5 134.333 22.5 135L144-66l50 76.5Z" />
              </g>
              <g filter="url(#f)">
                <path fill="#FA4340" d="M190.5-12.5C168.5 59.5 62 111.333 19 112L140.5-89l50 76.5Z" />
              </g>
              <g filter="url(#g)">
                <path fill="#14BB69" d="M194.5 279.5C172.5 207.5 66 155.667 23 155l121.5 201 50-76.5Z" />
              </g>
              <g filter="url(#h)">
                <path fill="#14BB69" d="M196.5 320.5C174.5 248.5 68 196.667 25 196l121.5 201 50-76.5Z" />
              </g>
            </g>
            <defs>
              <filter id="b" width="464" height="390" x="-69" y="-46" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
                <feFlood floodOpacity="0" result="BackgroundImageFix" />
                <feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
                <feGaussianBlur result="effect1_foregroundBlur_69_17998" stdDeviation="18" />
              </filter>
              <filter id="c" width="265" height="273" x="-99" y="6" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
                <feFlood floodOpacity="0" result="BackgroundImageFix" />
                <feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
                <feGaussianBlur result="effect1_foregroundBlur_69_17998" stdDeviation="32" />
              </filter>
              <filter id="d" width="265" height="273" x="-113" y="12" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
                <feFlood floodOpacity="0" result="BackgroundImageFix" />
                <feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
                <feGaussianBlur result="effect1_foregroundBlur_69_17998" stdDeviation="32" />
              </filter>
              <filter id="e" width="299.5" height="329" x="-41.5" y="-130" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
                <feFlood floodOpacity="0" result="BackgroundImageFix" />
                <feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
                <feGaussianBlur result="effect1_foregroundBlur_69_17998" stdDeviation="32" />
              </filter>
              <filter id="f" width="299.5" height="329" x="-45" y="-153" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
                <feFlood floodOpacity="0" result="BackgroundImageFix" />
                <feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
                <feGaussianBlur result="effect1_foregroundBlur_69_17998" stdDeviation="32" />
              </filter>
              <filter id="g" width="299.5" height="329" x="-41" y="91" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
                <feFlood floodOpacity="0" result="BackgroundImageFix" />
                <feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
                <feGaussianBlur result="effect1_foregroundBlur_69_17998" stdDeviation="32" />
              </filter>
              <filter id="h" width="299.5" height="329" x="-39" y="132" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
                <feFlood floodOpacity="0" result="BackgroundImageFix" />
                <feBlend in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
                <feGaussianBlur result="effect1_foregroundBlur_69_17998" stdDeviation="32" />
              </filter>
            </defs>
          </svg>
        )
    case "ollama":
      return (
        <svg className={classStr} viewBox="0 0 646 854" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M140.629 0.239929C132.66 1.52725 123.097 5.69568 116.354 10.845C95.941 26.3541 80.1253 59.2728 73.4435 100.283C70.9302 115.792 69.2138 137.309 69.2138 153.738C69.2138 173.109 71.4819 197.874 74.7309 214.977C75.4665 218.778 75.8343 222.15 75.5278 222.395C75.2826 222.64 72.2788 225.092 68.9072 227.789C57.3827 236.984 44.2029 251.145 35.1304 264.08C17.7209 288.784 6.44151 316.86 1.72133 347.265C-0.117698 359.28 -0.608106 383.555 0.863118 395.57C4.11207 423.278 12.449 446.695 26.7321 468.151L31.391 475.078L30.0424 477.346C20.4794 493.407 12.3264 516.64 8.52575 538.953C5.522 556.608 5.15419 561.328 5.15419 584.99C5.15419 608.837 5.4607 613.557 8.28054 630.047C11.6521 649.786 18.5178 670.689 26.1804 684.605C28.6938 689.141 34.8239 698.581 35.5595 699.072C35.8047 699.194 35.0691 701.462 33.9044 704.098C25.077 723.408 17.537 749.093 14.4106 770.733C12.2038 785.567 11.8973 790.349 11.8973 805.981C11.8973 825.903 13.0007 835.589 17.1692 851.466L17.7822 853.795H44.019H70.3172L68.6007 850.546C57.9957 830.93 57.0149 794.517 66.1487 758.166C70.3172 741.369 75.0374 729.048 83.8647 712.067L89.1366 701.769V695.455C89.1366 689.57 89.014 688.896 87.1137 685.034C85.6424 682.091 83.6808 679.578 80.1866 676.145C74.2404 670.383 69.9494 664.314 66.5165 656.835C51.4365 624.1 48.494 575.489 59.0991 534.049C63.5128 516.762 70.8076 501.376 78.4702 492.978C83.6808 487.215 86.378 480.779 86.378 474.097C86.378 467.17 83.926 461.469 78.4089 455.523C62.5932 438.604 52.8464 418.006 49.3522 394.038C44.3868 359.893 53.3981 322.683 73.8726 293.198C93.9181 264.263 122.055 245.689 153.503 240.724C160.552 239.559 173.732 239.743 181.088 241.092C189.119 242.502 194.145 242.072 199.295 239.62C205.67 236.617 208.858 232.877 212.597 224.295C215.907 216.633 218.482 212.464 225.409 203.821C233.746 193.461 241.776 186.411 254.649 177.89C269.362 168.266 286.097 161.278 302.771 157.906C308.839 156.68 311.659 156.496 323 156.496C334.341 156.496 337.161 156.68 343.229 157.906C367.688 162.872 391.964 175.5 411.335 193.399C415.503 197.261 425.495 209.644 428.683 214.794C429.909 216.816 432.055 221.108 433.403 224.295C437.142 232.877 440.33 236.617 446.705 239.62C451.671 242.011 456.881 242.502 464.605 241.214C476.804 239.13 486.183 239.314 498.137 241.766C538.841 249.98 574.273 283.512 589.966 328.446C603.636 367.862 599.774 409.118 579.422 440.626C575.989 445.96 572.556 450.251 567.591 455.523C556.863 466.986 556.863 481.208 567.53 492.978C585.062 512.165 596.035 559.367 592.724 600.99C590.518 628.453 583.468 653.035 573.782 666.95C572.066 669.402 568.511 673.57 565.813 676.145C562.319 679.578 560.358 682.091 558.886 685.034C556.986 688.896 556.863 689.57 556.863 695.455V701.769L562.135 712.067C570.963 729.048 575.683 741.369 579.851 758.166C588.863 794.027 588.066 829.704 577.767 849.995C576.909 851.711 576.173 853.305 576.173 853.489C576.173 853.673 587.882 853.795 602.226 853.795H628.218L628.892 851.159C629.26 849.75 629.873 847.604 630.179 846.378C630.854 843.681 632.202 835.712 633.306 828.049C634.348 820.325 634.348 791.881 633.306 783.299C629.383 752.158 622.823 727.454 612.096 704.098C610.931 701.462 610.195 699.194 610.44 699.072C610.747 698.888 612.463 696.436 614.302 693.677C627.666 673.448 635.88 648.008 640.049 614.415C641.152 605.158 641.152 565.374 640.049 556.485C637.106 533.559 633.551 517.988 627.666 502.234C625.214 495.675 618.716 481.821 615.958 477.346L614.609 475.078L619.268 468.151C633.551 446.695 641.888 423.278 645.137 395.57C646.608 383.555 646.118 359.28 644.279 347.265C639.497 316.798 628.279 288.845 644.279 264.08C639.497 264.08 628.279 264.08 610.87 264.08C601.797 251.145 588.617 236.984 577.093 227.789C573.721 225.092 570.717 222.64 570.472 222.395C570.166 222.15 570.534 218.778 571.269 214.977C578.687 176.296 578.441 128.053 570.656 90.3524C563.913 57.4951 551.653 31.3808 535.837 16.3008C523.209 4.28578 510.336 -0.863507 494.888 0.11731C459.456 2.20154 430.89 42.9667 419.61 107.21C417.771 117.57 416.178 129.708 416.178 133.018C416.178 134.305 415.932 135.347 415.626 135.347C415.319 135.347 412.929 134.121 410.354 132.589C383.014 116.405 352.608 107.762 323 107.762C293.392 107.762 262.986 116.405 235.646 132.589C233.071 134.121 230.681 135.347 230.374 135.347C230.068 135.347 229.822 134.305 229.822 133.018C229.822 129.585 228.167 117.08 226.39 107.21C216.152 49.5259 192.674 11.3354 161.472 1.71112C157.181 0.423799 144.982 -0.434382 140.629 0.239929ZM151.051 50.139C159.878 57.1273 169.686 77.1114 175.326 99.4863C176.368 103.532 177.471 108.191 177.778 109.907C178.023 111.563 178.697 115.302 179.249 118.183C181.64 131.179 182.743 145.217 182.866 162.32L182.927 179.178L178.697 185.43L174.468 191.744H164.598C153.074 191.744 141.61 193.216 130.637 196.158C126.714 197.139 122.913 198.12 122.178 198.304C121.013 198.549 120.829 198.181 120.155 193.154C116.538 165.875 116.722 135.654 120.707 110.52C125.12 82.5059 135.419 57.1273 145.472 49.6486C147.863 47.8708 148.292 47.9321 151.051 50.139ZM500.589 49.7098C506.658 54.1848 513.34 66.0772 518.305 81.2798C528.297 111.685 531.117 153.431 525.845 193.154C525.171 198.181 524.987 198.549 523.822 198.304C523.087 198.12 519.286 197.139 515.363 196.158C504.39 193.216 492.926 191.744 481.402 191.744H481.402C481.402 191.744 471.532 191.744 471.532 191.744L467.303 185.43L463.073 179.178L463.134 162.32C463.257 138.535 465.464 119.961 470.735 99.3024C476.314 77.1114 486.183 57.1273 494.949 50.139C497.708 47.9321 498.137 47.8708 500.589 49.7098ZM313.498 358.237C300.195 359.525 296.579 360.015 290.203 361.303C279.843 363.448 265.989 368.23 256.365 372.95C222.895 389.317 199.846 416.596 192.796 448.166C191.386 454.419 191.202 456.503 191.202 467.047C191.202 477.468 191.386 479.736 192.735 485.682C202.114 526.938 240.12 557.405 289.284 562.983C299.95 564.148 346.049 564.148 356.715 562.983C396.193 558.508 430.154 537.114 445.418 507.076C449.463 499.046 451.425 493.835 453.264 485.682C454.613 479.736 454.797 477.468 454.797 467.047C454.797 456.503 454.613 454.419 453.203 448.166C442.965 402.313 398.461 366.207 343.903 359.341C336.792 358.483 318.157 357.747 313.498 358.237ZM336.424 391.585C354.631 393.547 372.96 400.045 387.672 409.853C395.58 415.125 406.737 426.159 411.518 433.393C417.403 442.342 420.774 451.476 422.307 462.572C422.981 467.66 422.614 471.522 420.774 479.736C417.893 491.996 408.943 504.808 396.867 513.758C391.227 517.865 379.519 523.812 372.347 526.141C358.738 530.493 349.849 531.29 318.095 531.045C297.376 530.861 293.697 530.677 287.751 529.574C267.461 525.773 251.4 517.681 239.753 505.36C230.312 495.429 226.021 486.357 223.692 471.706C222.65 464.901 224.611 453.622 228.596 444.12C233.439 432.534 245.944 418.129 258.327 409.853C272.671 400.29 291.552 393.486 308.9 391.647C315.582 390.911 329.742 390.911 336.424 391.585ZM299.584 436.336C294.925 438.849 291.676 445.224 292.657 449.944C293.76 455.032 298.235 460.182 305.223 464.412C308.963 466.68 309.208 466.986 309.392 469.254C309.514 470.603 309.024 474.465 308.35 477.898C307.614 481.269 307.062 484.825 307.062 485.806C307.124 488.442 309.576 492.733 312.15 494.817C314.419 496.656 314.848 496.717 321.223 496.901C327.047 497.085 328.273 496.962 330.602 495.859C336.61 492.916 338.142 487.522 335.935 477.162C334.096 468.519 334.464 467.17 339.062 464.534C343.904 461.714 349.054 456.749 350.586 453.377C353.529 446.941 350.831 439.646 344.333 436.274C342.74 435.477 340.778 435.11 337.897 435.11C333.422 435.11 330.541 436.152 325.269 439.523L322.265 441.424L320.365 440.259C312.58 435.661 311.17 435.11 306.449 435.171C303.078 435.171 301.239 435.477 299.584 436.336ZM150.744 365.165C139.894 368.598 131.802 376.567 127.634 387.908C125.611 393.303 124.63 401.824 125.488 406.421C127.511 417.394 136.522 427.386 146.76 430.145C159.633 433.516 169.257 431.309 177.778 422.85C182.743 418.007 185.441 413.777 188.138 406.911C190.099 402.069 190.222 401.211 190.222 394.345L190.283 386.989L187.709 381.717C183.601 373.38 176.184 367.188 167.602 364.92C162.759 363.694 154.974 363.756 150.744 365.165ZM478.153 364.982C469.755 367.25 462.276 373.502 458.291 381.717L455.717 386.989L455.778 394.345C455.778 401.211 455.901 402.069 457.862 406.911C460.56 413.777 463.257 418.007 468.222 422.85C476.743 431.309 486.367 433.516 499.241 430.145C506.658 428.183 514.075 421.93 517.631 414.635C520.696 408.444 521.431 403.969 520.451 396.919C518.183 380.797 508.742 369.089 494.704 364.982C490.597 363.756 482.628 363.756 478.153 364.982Z" fill="currentColor" />
        </svg>
      )
    default:
      return (
        <svg className={classStr} id="b70acf0a-34b4-4bdf-9024-7496043ff915" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 18">
          <defs>
            <radialGradient id="oth-grad" cx="13428.81" cy="3518.86" r="56.67" gradientTransform="translate(-2005.33 -518.83) scale(0.15)" gradientUnits="userSpaceOnUse">
              <stop offset="0.18" stopColor="#5ea0ef" />
              <stop offset="1" stopColor="#0078d4" />
            </radialGradient>
            <linearGradient id="oth-grad-lin-1" x1="4.4" y1="11.48" x2="4.37" y2="7.53" gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="#ccc" />
              <stop offset="1" stopColor="#fcfcfc" />
            </linearGradient>
            <linearGradient id="oth-grad-lin-2" x1="10.13" y1="15.45" x2="10.13" y2="11.9" gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="#ccc" />
              <stop offset="1" stopColor="#fcfcfc" />
            </linearGradient>
            <linearGradient id="oth-grad-lin-3" x1="14.18" y1="11.15" x2="14.18" y2="7.38" gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="#ccc" />
              <stop offset="1" stopColor="#fcfcfc" />
            </linearGradient>
          </defs>
          <path d="M14.21,15.72A8.5,8.5,0,0,1,3.79,2.28l.09-.06a8.5,8.5,0,0,1,10.33,13.5" fill="url(#oth-grad)" />
          <path d="M6.69,7.23A13,13,0,0,1,15.6,3.65a8.47,8.47,0,0,0-1.49-1.44,14.34,14.34,0,0,0-4.69,1.1A12.54,12.54,0,0,0,5.34,6.13,2.76,2.76,0,0,1,6.69,7.23Z" fill="#fff" opacity="0.6" />
          <path d="M2.48,10.65a17.86,17.86,0,0,0-.83,2.62,7.82,7.82,0,0,0,.62.92c.18.23.35.44.55.65A17.94,17.94,0,0,1,3.9,11.37,2.76,2.76,0,0,1,2.48,10.65Z" fill="#fff" opacity="0.6" />
          <path d="M3.46,6.11a12,12,0,0,1-.69-2.94,8.15,8.15,0,0,0-1.1,1.45A12.69,12.69,0,0,0,2.24,7,2.69,2.69,0,0,1,3.46,6.11Z" fill="#f2f2f2" opacity="0.55" />
          <circle cx="4.38" cy="8.68" r="2.73" fill="url(#oth-grad-lin-1)" />
          <path d="M8.36,13.67A1.77,1.77,0,0,1,8.9,12.4a11.88,11.88,0,0,1-2.53-1.86,2.74,2.74,0,0,1-1.49.83,13.1,13.1,0,0,0,1.45,1.28A12.12,12.12,0,0,0,8.38,13.9,1.79,1.79,0,0,1,8.36,13.67Z" fill="#f2f2f2" opacity="0.55" />
          <path d="M14.66,13.88a12,12,0,0,1-2.76-.32.41.41,0,0,1,0,.11,1.75,1.75,0,0,1-.51,1.24,13.69,13.69,0,0,0,3.42.24A8.21,8.21,0,0,0,16,13.81,11.5,11.5,0,0,1,14.66,13.88Z" fill="#f2f2f2" opacity="0.55" />
          <circle cx="10.13" cy="13.67" r="1.78" fill="url(#oth-grad-lin-2)" />
          <path d="M12.32,8.93a1.83,1.83,0,0,1,.61-1A25.5,25.5,0,0,1,8.47,3.79a16.91,16.91,0,0,1-2-2.92,7.64,7.64,0,0,0-1.09.42A18.14,18.14,0,0,0,7.53,4.47,26.44,26.44,0,0,0,12.32,8.93Z" fill="#f2f2f2" opacity="0.7" />
          <circle cx="14.18" cy="9.27" r="1.89" fill="url(#oth-grad-lin-3)" />
          <path d="M17.35,10.54,17,10.37l0,0-.3-.16-.06,0L16.38,10l-.07,0L16,9.8a1.76,1.76,0,0,1-.64.92c.12.08.25.15.38.22l.08.05.35.19,0,0,.86.45h0a8.63,8.63,0,0,0,.29-1.11Z" fill="#f2f2f2" opacity="0.55" />
          <circle cx="4.38" cy="8.68" r="2.73" fill="url(#oth-grad-lin-1)" />
          <circle cx="10.13" cy="13.67" r="1.78" fill="url(#oth-grad-lin-2)" />
        </svg>
      )
  }
}

function getChannelIconKey(type: string, targetHint: string): string {
  if (type === "email") return "email"
  if (type === "telegram") return "telegram"
  if (type === "apprise_url") {
    const hint = targetHint.toLowerCase()
    if (hint.startsWith("ntfy")) return "ntfy"
    if (hint.startsWith("slack")) return "slack"
    if (hint.startsWith("discord")) return "discord"
    if (hint.startsWith("json") || hint.startsWith("webhook") || hint.startsWith("http")) return "webhook"
  }
  return "other"
}

function getChannelKindLabel(type: string, targetHint: string): string {
  if (type === "apprise_url") {
    const parts = targetHint.split("://", 1)
    return parts[0] || "service"
  }
  return type
}

function errMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

// Rotation-pool key health -> status dot + label. A cooled-down key is
// resting after a rate-limit; exhausted has spent its daily budget.
function geminiKeyDot(health: apiClient.GeminiKeyHealth): DotState {
  switch (health) {
    case "healthy":
      return "clean"
    case "cooldown":
      return "pending"
    case "exhausted":
      return "threat"
    default:
      return "idle"
  }
}

function geminiKeyHealthLabel(health: apiClient.GeminiKeyHealth): string {
  switch (health) {
    case "healthy":
      return "Healthy"
    case "cooldown":
      return "Cooling down"
    case "exhausted":
      return "Daily budget spent"
    default:
      return health
  }
}

// --- SMTP card (§8: a passing Send Test gates the Save action) ---

function SmtpCard() {
  const queryClient = useQueryClient()
  const settings = useQuery({ queryKey: ["settings", "smtp"], queryFn: apiClient.getSmtpSettings })

  const [host, setHost] = useState("")
  const [port, setPort] = useState("587")
  const [security, setSecurity] = useState("starttls")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [fromAddr, setFromAddr] = useState("")
  const [fromName, setFromName] = useState("")
  const [testTo, setTestTo] = useState("")
  const [hydrated, setHydrated] = useState(false)
  // §8: Send Test gates Save. A passing test against the *current form
  // values* unlocks Save; editing any field re-locks it.
  const [testedOk, setTestedOk] = useState(false)

  useEffect(() => {
    if (settings.data && !hydrated) {
      setHost(settings.data.host ?? "")
      setPort(String(settings.data.port ?? 587))
      setSecurity(settings.data.security ?? "starttls")
      setUsername(settings.data.username ?? "")
      setFromAddr(settings.data.from_addr ?? "")
      setFromName(settings.data.from_name ?? "")
      setHydrated(true)
    }
  }, [settings.data, hydrated])

  const formValues = (): apiClient.SmtpSettingsPatch => ({
    host,
    port: Number(port) || 587,
    security,
    username: username || null,
    // No password typed = keep/fall back to the stored one.
    password: password ? password : null,
    from_addr: fromAddr,
    from_name: fromName || null,
  })

  function edited<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v)
      setTestedOk(false)
    }
  }
  const setHostE = edited(setHost)
  const setPortE = edited(setPort)
  const setSecurityE = edited(setSecurity)
  const setUsernameE = edited(setUsername)
  const setPasswordE = edited(setPassword)
  const setFromAddrE = edited(setFromAddr)
  const setFromNameE = edited(setFromName)

  const save = useMutation({
    mutationFn: () => apiClient.putSmtpSettings(formValues()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["settings", "smtp"] })
      setPassword("")
      toast.success("SMTP settings saved")
    },
    onError: (err) => toast.error(errMessage(err, "Could not save SMTP settings")),
  })

  const test = useMutation({
    // Tests the unsaved form values so Save can require a passing test.
    mutationFn: () => apiClient.testSmtp(testTo, formValues()),
    onSuccess: (result) => {
      if (result.ok) {
        setTestedOk(true)
        toast.success(`${result.detail} — Save is unlocked`)
      } else {
        toast.error(result.detail)
      }
    },
    onError: (err) => toast.error(errMessage(err, "Test failed")),
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {getChannelIcon("email", "size-5")}
          Email (SMTP)
        </CardTitle>
        <CardDescription>
          Alert emails send through your own SMTP server. Send a test first
          — Save unlocks once a test delivery succeeds. Gmail needs an App
          Password (Google Account, Security, 2-Step Verification).
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="smtp-host">Server host</Label>
              <Input
                id="smtp-host"
                required
                placeholder="smtp.example.com"
                value={host}
                onChange={(e) => setHostE(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="smtp-port">Port</Label>
              <Input
                id="smtp-port"
                inputMode="numeric"
                value={port}
                onChange={(e) => setPortE(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="smtp-security">Connection security</Label>
            <CustomSelect
              id="smtp-security"
              value={security}
              onChange={setSecurityE}
              options={[
                { value: "starttls", label: "STARTTLS (port 587, recommended)" },
                { value: "tls", label: "TLS/SSL (port 465)" },
                { value: "none", label: "None (unencrypted, LAN relays only)" },
              ]}
            />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="smtp-user">Username</Label>
              <Input
                id="smtp-user"
                autoComplete="off"
                value={username}
                onChange={(e) => setUsernameE(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="smtp-pass">
                Password{" "}
                {settings.data?.has_password && (
                  <span className="text-mute">(stored — leave blank to keep)</span>
                )}
              </Label>
              <Input
                id="smtp-pass"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPasswordE(e.target.value)}
              />
            </div>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="smtp-from">From address</Label>
              <Input
                id="smtp-from"
                required
                placeholder="wardress@example.com"
                value={fromAddr}
                onChange={(e) => setFromAddrE(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="smtp-from-name">From name</Label>
              <Input
                id="smtp-from-name"
                placeholder="Wardress"
                value={fromName}
                onChange={(e) => setFromNameE(e.target.value)}
              />
            </div>
          </div>
          <div className="flex flex-wrap items-end justify-between gap-4 border-t border-hairline pt-4">
            <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-end">
              <div className="space-y-1.5">
                <Label htmlFor="smtp-test-to">Send a test to</Label>
                <Input
                  id="smtp-test-to"
                  type="email"
                  placeholder="you@example.com"
                  className="w-56"
                  value={testTo}
                  onChange={(e) => setTestTo(e.target.value)}
                />
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!host || !fromAddr || !testTo || test.isPending}
                onClick={() => test.mutate()}
              >
                <Send />
                {test.isPending ? "Sending" : "Send test"}
              </Button>
            </div>
            <Button
              type="submit"
              variant="outline"
              size="sm"
              disabled={!testedOk || save.isPending}
              title={testedOk ? undefined : "Send a successful test first"}
            >
              Save SMTP settings
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

// --- Telegram card (§8 setup flow: token -> /start -> captured chat) ---

function TelegramCard() {
  const queryClient = useQueryClient()
  const settings = useQuery({
    queryKey: ["settings", "telegram"],
    queryFn: apiClient.getTelegramSettings,
    // While waiting for /start, poll so the captured chat appears live.
    refetchInterval: (query) =>
      query.state.data?.configured && !query.state.data.chat_id ? 4000 : false,
  })
  const [token, setToken] = useState("")
  // The bot's free-text assistant acts as a real RBAC user (no pseudo-actor
  // free pass). Without a linked user the bot answers slash commands only.
  const users = useQuery({ queryKey: ["users"], queryFn: apiClient.listUsers })

  const save = useMutation({
    mutationFn: (value: string | null) => apiClient.putTelegramSettings(value),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["settings", "telegram"] })
      setToken("")
      toast.success(
        data.configured
          ? "Bot token saved — now open your bot in Telegram and send /start"
          : "Telegram configuration cleared"
      )
    },
    onError: (err) => toast.error(errMessage(err, "Could not save the bot token")),
  })

  const test = useMutation({
    mutationFn: apiClient.testTelegram,
    onSuccess: (result) => (result.ok ? toast.success(result.detail) : toast.error(result.detail)),
    onError: (err) => toast.error(errMessage(err, "Test failed")),
  })

  const linkActingUser = useMutation({
    mutationFn: (actingUserId: string) =>
      apiClient.putTelegramSettings(null, actingUserId),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["settings", "telegram"] })
      toast.success(
        data.acting_user_id
          ? `Assistant now acts as ${data.acting_user_email}`
          : "Assistant user cleared"
      )
    },
    onError: (err) => toast.error(errMessage(err, "Could not link the assistant user")),
  })

  const s = settings.data

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {getChannelIcon("telegram", "size-5")}
          Telegram
        </CardTitle>
        <CardDescription>
          Two-way bot: alert pushes plus /status, /sites, /scan, /ack, /mute
          and /explain from your phone.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ol className="list-decimal space-y-1 pl-5 text-body-sm text-charcoal">
          <li>
            Message <span className="text-code-md text-body">@BotFather</span> in Telegram and
            create a bot with <span className="text-code-md text-body">/newbot</span>.
          </li>
          <li>Paste the token it gives you below and save.</li>
          <li>
            Start the bot container (
            <span className="text-code-md text-body">docker compose --profile telegram up -d</span>
            ), open your bot, and send{" "}
            <span className="text-code-md text-body">/start</span> — the chat is captured
            automatically.
          </li>
        </ol>

        {s?.configured ? (
          <div className="space-y-2 rounded-md border border-hairline bg-surface-elevated p-4">
            <div className="flex items-center gap-2 text-body-sm text-body">
              <StatusDot state={s.chat_id ? "clean" : "pending"} />
              {s.chat_id
                ? `Connected — chat ${s.chat_id} captured ${s.chat_captured_at ?? ""}`
                : "Token saved — waiting for /start from your Telegram account"}
            </div>
            <p className="text-caption text-mute">Token {s.token_hint}</p>
          </div>
        ) : null}

        {/* Natural-language assistant: which Wardress user the bot acts as.
            Actions run with this user's role and are audited under them. */}
        {s?.configured && s.chat_id ? (
          <div className="space-y-2 rounded-md border border-hairline bg-surface-elevated p-4">
            <div className="flex items-center gap-2 text-body-sm text-body">
              <StatusDot state={s.acting_user_id ? "clean" : "pending"} />
              Natural-language assistant
              {s.acting_user_id ? (
                <span className="text-caption text-mute">acts as {s.acting_user_email}</span>
              ) : (
                <span className="text-caption text-mute">not linked — slash commands only</span>
              )}
            </div>
            <p className="text-caption text-mute">
              Free-text messages route through the same guarded actions as the web
              assistant, running with the linked user&rsquo;s role. High-impact actions
              still ask for confirmation with inline buttons.
            </p>
            <div className="flex flex-col items-stretch gap-2 pt-1 sm:flex-row sm:items-end">
              <div className="min-w-0 flex-1 space-y-1.5">
                <Label htmlFor="tg-acting-user">Acts as user</Label>
                <CustomSelect
                  id="tg-acting-user"
                  value={s.acting_user_id ?? ""}
                  disabled={linkActingUser.isPending || users.isLoading}
                  onChange={(val) => linkActingUser.mutate(val)}
                  options={[
                    { value: "", label: "None (disable assistant)" },
                    ...(users.data ?? []).map((u) => ({
                      value: u.id,
                      label: `${u.email} (${u.role})`,
                    })),
                  ]}
                />
              </div>
            </div>
          </div>
        ) : null}

        <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-end">
          <div className="min-w-0 flex-1 space-y-1.5 sm:min-w-64">
            <Label htmlFor="tg-token">Bot token</Label>
            <Input
              id="tg-token"
              autoComplete="off"
              placeholder="1234567890:AA..."
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={!token || save.isPending}
            onClick={() => save.mutate(token)}
          >
            Save token
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!s?.configured || !s.chat_id || test.isPending}
            onClick={() => test.mutate()}
          >
            <Send />
            Send test message
          </Button>
          {s?.configured && (
            <Button
              variant="ghost"
              size="sm"
              disabled={save.isPending}
              onClick={() => save.mutate("")}
            >
              Disconnect
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// --- AI providers card (Gemini + Ollama, §8) ---

function AiCard() {
  const queryClient = useQueryClient()
  const gemini = useQuery({ queryKey: ["settings", "gemini"], queryFn: apiClient.getGeminiSettings })
  const ollama = useQuery({ queryKey: ["settings", "ollama"], queryFn: apiClient.getOllamaSettings })

  const [apiKey, setApiKey] = useState("")
  const [keyLabel, setKeyLabel] = useState("")
  const [ollamaModel, setOllamaModel] = useState("")
  const [ollamaHydrated, setOllamaHydrated] = useState(false)

  useEffect(() => {
    if (ollama.data && !ollamaHydrated) {
      setOllamaModel(ollama.data.model ?? "")
      setOllamaHydrated(true)
    }
  }, [ollama.data, ollamaHydrated])

  const addKey = useMutation({
    mutationFn: (body: { api_key: string; label?: string }) => apiClient.addGeminiKey(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["settings", "gemini"] })
      setApiKey("")
      setKeyLabel("")
      toast.success("Key added to the pool")
    },
    onError: (err) => toast.error(errMessage(err, "Could not add the key")),
  })

  const removeKey = useMutation({
    mutationFn: (keyId: string) => apiClient.removeGeminiKey(keyId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["settings", "gemini"] })
      toast.success("Key removed from the pool")
    },
    onError: (err) => toast.error(errMessage(err, "Could not remove the key")),
  })

  const testGeminiM = useMutation({
    mutationFn: apiClient.testGemini,
    onSuccess: (r) => (r.ok ? toast.success(r.detail) : toast.error(r.detail)),
    onError: (err) => toast.error(errMessage(err, "Test failed")),
  })

  const keys = gemini.data?.keys ?? []

  const saveOllama = useMutation({
    mutationFn: (enabled: boolean) =>
      apiClient.putOllamaSettings({ enabled, model: ollamaModel || null }),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["settings", "ollama"] })
      toast.success(data.enabled ? "Ollama enabled" : "Ollama settings saved")
    },
    onError: (err) => toast.error(errMessage(err, "Could not save Ollama settings")),
  })

  const testOllamaM = useMutation({
    mutationFn: apiClient.testOllama,
    onSuccess: (r) => (r.ok ? toast.success(r.detail) : toast.error(r.detail)),
    onError: (err) => toast.error(errMessage(err, "Test failed")),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {getChannelIcon("gemini", "size-5")}
          AI analysis
        </CardTitle>
        <CardDescription>
          Optional. Ambiguous scans get a semantic second opinion, and incident
          pages gain an &ldquo;Explain this incident&rdquo; summary. Detection works fully
          without it — an unavailable provider is skipped silently, never
          blocking a scan.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-body-sm text-body">
              <StatusDot state={keys.length > 0 ? "clean" : "idle"} />
              {getChannelIcon("gemini", "size-4.5 text-accent-blue")}
              Google Gemini ({gemini.data?.model ?? "gemini-flash-latest"})
              {keys.length > 0 && (
                <span className="text-caption text-mute">
                  {keys.length} key{keys.length === 1 ? "" : "s"} in rotation
                </span>
              )}
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={keys.length === 0 || testGeminiM.isPending}
              onClick={() => testGeminiM.mutate()}
            >
              {testGeminiM.isPending ? "Testing" : "Test pool"}
            </Button>
          </div>

          {/* Rotation pool — the agent and ambiguous-scan calls fail over
              across these keys, each with its own free-tier budget. */}
          {keys.length > 0 && (
            <ul className="divide-y divide-hairline rounded-md border border-hairline">
              {keys.map((key) => (
                <li key={key.id} className="flex items-center gap-3 px-3 py-2.5">
                  <StatusDot state={geminiKeyDot(key.health)} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-body-sm text-body">
                      <span className="truncate">{key.label || "unnamed key"}</span>
                      {key.hint && (
                        <span className="text-caption text-mute">{key.hint}</span>
                      )}
                    </div>
                    <p className="text-caption text-mute">
                      {geminiKeyHealthLabel(key.health)}
                      {key.daily_budget > 0 && (
                        <> · {key.used_today}/{key.daily_budget} today</>
                      )}
                      {key.last_used && <> · last used {key.last_used}</>}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Remove ${key.label || "key"}`}
                    disabled={removeKey.isPending}
                    onClick={() => removeKey.mutate(key.id)}
                  >
                    <Trash2 className="text-mute" />
                  </Button>
                </li>
              ))}
            </ul>
          )}

          <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-end">
            <div className="min-w-0 flex-1 space-y-1.5">
              <Label htmlFor="gemini-key">Add API key</Label>
              <Input
                id="gemini-key"
                type="password"
                autoComplete="off"
                placeholder="AIza..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </div>
            <div className="space-y-1.5 sm:w-40">
              <Label htmlFor="gemini-label">Label</Label>
              <Input
                id="gemini-label"
                autoComplete="off"
                placeholder="optional"
                value={keyLabel}
                onChange={(e) => setKeyLabel(e.target.value)}
              />
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={apiKey.trim().length < 8 || addKey.isPending}
              onClick={() => addKey.mutate({ api_key: apiKey.trim(), label: keyLabel.trim() })}
            >
              {addKey.isPending ? "Adding" : "Add key"}
            </Button>
          </div>
          <p className="text-caption text-mute">
            Add several free-tier keys — Wardress rotates across them and cools
            down any that hit a rate limit, so the assistant keeps working well
            inside the free quota.
          </p>
        </div>

        <div className="space-y-3 border-t border-hairline pt-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-body-sm text-body">
              <StatusDot state={ollama.data?.enabled ? "clean" : "idle"} />
              {getChannelIcon("ollama", "size-4.5 text-ink")}
              Ollama (local, no cloud)
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={!ollama.data?.enabled || testOllamaM.isPending}
                onClick={() => testOllamaM.mutate()}
              >
                {testOllamaM.isPending ? "Testing" : "Test"}
              </Button>
            </div>
          </div>
          <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-end">
            <div className="min-w-0 flex-1 space-y-1.5 sm:min-w-64">
              <Label htmlFor="ollama-model">Model</Label>
              <Input
                id="ollama-model"
                placeholder="llama3.2"
                value={ollamaModel}
                onChange={(e) => setOllamaModel(e.target.value)}
              />
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={saveOllama.isPending || (!ollama.data?.enabled && !ollamaModel)}
              onClick={() => saveOllama.mutate(!ollama.data?.enabled)}
            >
              {ollama.data?.enabled ? "Disable" : "Enable"}
            </Button>
          </div>
          <p className="text-caption text-mute">
            Needs the ollama compose profile running (
            <span className="text-code-md">docker compose --profile ollama up -d</span>) with the
            model pulled. Gemini is preferred when both are enabled.
          </p>
        </div>
      </CardContent>
    </Card>
  )
}

// --- Notification channels card ---

const CHANNEL_PRESETS: {
  key: string
  label: string
  kind: string
  placeholder: string
  hint: string
  recommended?: boolean
}[] = [
  {
    key: "ntfy",
    label: "ntfy",
    kind: "ntfy",
    placeholder: "ntfy://your-private-topic",
    hint: "Easiest push option: pick a unique topic, subscribe in the ntfy app.",
    recommended: true,
  },
  {
    key: "discord",
    label: "Discord",
    kind: "discord",
    placeholder: "discord://webhook_id/webhook_token",
    hint: "From a channel webhook URL: discord.com/api/webhooks/{id}/{token}.",
  },
  {
    key: "slack",
    label: "Slack",
    kind: "slack",
    placeholder: "slack://TokenA/TokenB/TokenC",
    hint: "From an incoming-webhook URL's three token segments.",
  },
  {
    key: "webhook",
    label: "Webhook",
    kind: "webhook",
    placeholder: "json://host/path or https URL via json://",
    hint: "POSTs a JSON payload to any endpoint you run.",
  },
  {
    key: "other",
    label: "Other",
    kind: "apprise",
    placeholder: "scheme://... (any Apprise URL)",
    hint: "Any of the 100+ Apprise services — matrix://, gotify://, pover://, ...",
  },
]

function ChannelsCard() {
  const queryClient = useQueryClient()
  const channels = useQuery({ queryKey: ["channels"], queryFn: apiClient.listChannels })
  const sites = useQuery({ queryKey: ["sites"], queryFn: apiClient.listSites })

  const [dialogOpen, setDialogOpen] = useState(false)
  const [showScopeSelector, setShowScopeSelector] = useState(false)
  const [chanType, setChanType] = useState<ChannelType>("apprise_url")
  const [preset, setPreset] = useState(CHANNEL_PRESETS[0])
  const [name, setName] = useState("")
  const [to, setTo] = useState("")
  const [url, setUrl] = useState("")
  const [siteId, setSiteId] = useState<string>("")
  const [formError, setFormError] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () =>
      apiClient.createChannel({
        type: chanType,
        name,
        site_id: siteId || null,
        ...(chanType === "email" ? { to } : {}),
        ...(chanType === "apprise_url" ? { url, kind: preset.kind } : {}),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["channels"] })
      setDialogOpen(false)
      setShowScopeSelector(false)
      setName("")
      setTo("")
      setUrl("")
      setSiteId("")
      setFormError(null)
      toast.success("Channel added — send it a test")
    },
    onError: (err) => setFormError(errMessage(err, "Could not add the channel")),
  })

  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      apiClient.updateChannel(id, { is_active: active }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["channels"] }),
    onError: (err) => toast.error(errMessage(err, "Could not update the channel")),
  })

  const remove = useMutation({
    mutationFn: apiClient.deleteChannel,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["channels"] })
      toast.success("Channel removed")
    },
    onError: (err) => toast.error(errMessage(err, "Could not remove the channel")),
  })

  const test = useMutation({
    mutationFn: apiClient.testChannel,
    onSuccess: (r) => (r.ok ? toast.success(r.detail) : toast.error(r.detail)),
    onError: (err) => toast.error(errMessage(err, "Test failed")),
  })

  const siteName = (id: string | null) =>
    id ? (sites.data?.find((s) => s.id === id)?.name ?? "one site") : "All sites"

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle className="flex items-center gap-2">
              <svg className="size-4 shrink-0 text-purple-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                <path d="M13.73 21a2 2 0 0 1-3.46 0" />
              </svg>
              Alert channels
            </CardTitle>
            <CardDescription>
              Where flagged scans go. Channels apply to every site unless
              scoped to one; failures are recorded per delivery and shown on
              the Alerts page.
            </CardDescription>
          </div>
          <Dialog
            open={dialogOpen}
            onOpenChange={(open) => {
              setDialogOpen(open)
              if (!open) {
                setShowScopeSelector(false)
              }
            }}
          >
            <DialogTrigger asChild>
              <Button variant="outline" size="sm">
                <Plus />
                Add channel
              </Button>
            </DialogTrigger>
            <DialogContent className={cn("transition-all duration-300 ease-in-out sm:max-w-lg", showScopeSelector && "sm:max-w-3xl")}>
              <DialogHeader>
                <DialogTitle>Add an alert channel</DialogTitle>
                <DialogDescription>
                  Alerts fire when a scan's fused risk crosses the site's flag
                  threshold.
                </DialogDescription>
              </DialogHeader>
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  setFormError(null)
                  create.mutate()
                }}
                className="flex flex-col gap-5 overflow-hidden"
              >
                <div className="relative flex w-full transition-all duration-300 ease-in-out items-start">
                  
                  {/* Left Pane (Main Form) */}
                  <div
                    onClick={() => {
                      if (showScopeSelector) setShowScopeSelector(false)
                    }}
                    className={cn(
                      "flex flex-col gap-5 transition-all duration-300 ease-in-out shrink-0 w-full",
                      showScopeSelector ? "sm:w-[410px] opacity-80 cursor-pointer" : ""
                    )}
                  >
                    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                      {CHANNEL_PRESETS.map((p) => {
                        const isSelected = chanType === "apprise_url" && preset.key === p.key
                        return (
                          <button
                            key={p.key}
                            type="button"
                            onClick={() => {
                              setPreset(p)
                              setChanType("apprise_url")
                            }}
                            className={cn(
                              "flex flex-col items-center justify-center p-3 rounded-lg border text-center transition-all cursor-pointer",
                              isSelected
                                ? "border-accent-blue bg-accent-blue/5 text-ink font-semibold"
                                : "border-hairline-strong bg-surface-elevated text-charcoal hover:border-hairline hover:text-ink"
                            )}
                          >
                            <div className="mb-1.5 flex items-center justify-center h-8 text-charcoal">
                              {getChannelIcon(p.key, "size-6.5")}
                            </div>
                            <span className="text-[11px] font-medium tracking-wide uppercase">{p.label}</span>
                            {p.recommended && (
                              <span className="mt-1 text-[8px] text-accent-green font-mono uppercase tracking-widest font-bold">Recommended</span>
                            )}
                          </button>
                        )
                      })}
                      <button
                        type="button"
                        onClick={() => setChanType("email")}
                        className={cn(
                          "flex flex-col items-center justify-center p-3 rounded-lg border text-center transition-all cursor-pointer",
                          chanType === "email"
                            ? "border-accent-blue bg-accent-blue/5 text-ink font-semibold"
                            : "border-hairline-strong bg-surface-elevated text-charcoal hover:border-hairline hover:text-ink"
                        )}
                      >
                        <div className="mb-1.5 flex items-center justify-center h-8 text-charcoal">
                          {getChannelIcon("email", "size-6.5")}
                        </div>
                        <span className="text-[11px] font-medium tracking-wide uppercase">Email</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setChanType("telegram")}
                        className={cn(
                          "flex flex-col items-center justify-center p-3 rounded-lg border text-center transition-all cursor-pointer",
                          chanType === "telegram"
                            ? "border-accent-blue bg-accent-blue/5 text-ink font-semibold"
                            : "border-hairline-strong bg-surface-elevated text-charcoal hover:border-hairline hover:text-ink"
                        )}
                      >
                        <div className="mb-1.5 flex items-center justify-center h-8 text-charcoal">
                          {getChannelIcon("telegram", "size-6.5")}
                        </div>
                        <span className="text-[11px] font-medium tracking-wide uppercase">Telegram</span>
                      </button>
                    </div>

                    <div className="flex flex-col gap-2">
                      <Label htmlFor="chan-name">Name</Label>
                      <Input
                        id="chan-name"
                        required
                        placeholder="Ops alerts"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                      />
                    </div>

                    {chanType === "email" && (
                      <div className="flex flex-col gap-2">
                        <Label htmlFor="chan-to">Recipient address</Label>
                        <Input
                          id="chan-to"
                          type="email"
                          required
                          placeholder="oncall@example.com"
                          value={to}
                          onChange={(e) => setTo(e.target.value)}
                        />
                        <p className="text-caption text-mute">
                          Sends through the SMTP settings above.
                        </p>
                      </div>
                    )}

                    {chanType === "apprise_url" && (
                      <div className="flex flex-col gap-2">
                        <Label htmlFor="chan-url">Service URL</Label>
                        <Input
                          id="chan-url"
                          required
                          autoComplete="off"
                          placeholder={preset.placeholder}
                          value={url}
                          onChange={(e) => setUrl(e.target.value)}
                        />
                        <p className="text-caption text-mute">{preset.hint}</p>
                      </div>
                    )}

                    {chanType === "telegram" && (
                      <p className="text-body-sm text-charcoal">
                        Pushes to the Telegram chat captured in the Telegram card
                        above — configure that first.
                      </p>
                    )}

                    <div className="flex flex-col gap-2">
                      <Label htmlFor="chan-site">Scope</Label>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          setShowScopeSelector((prev) => !prev)
                        }}
                        className={cn(
                          "w-full h-9 rounded-md border border-hairline-strong bg-surface-elevated px-3 text-left text-xs font-normal text-ink outline-none focus:border-white/25 transition-colors flex items-center justify-between cursor-pointer select-none",
                          showScopeSelector && "border-accent-blue bg-accent-blue/5"
                        )}
                      >
                        <span className="truncate">
                          {siteId === "" ? "All sites" : `Only ${sites.data?.find((s) => s.id === siteId)?.name ?? "selected site"}`}
                        </span>
                        <span className="font-mono text-[9px] uppercase tracking-wider text-mute border border-hairline px-1.5 py-0.5 rounded bg-surface-deep group-hover:text-ink transition-colors">
                          Choose site
                        </span>
                      </button>
                    </div>
                  </div>

                  {/* Vertical divider */}
                  {showScopeSelector && (
                    <div className="hidden sm:block w-[1px] self-stretch bg-hairline-strong mx-6 shrink-0 transition-opacity duration-300" />
                  )}

                  {/* Right Pane (Scope selector) */}
                  <div
                    className={cn(
                      "transition-all duration-300 ease-in-out shrink-0 flex flex-col max-h-[380px] overflow-y-auto scrollbar-none",
                      showScopeSelector 
                        ? "w-full sm:w-[250px] opacity-100 translate-x-0 visible" 
                        : "w-0 opacity-0 translate-x-12 invisible absolute"
                    )}
                  >
                    <div className="flex items-center justify-between border-b border-hairline pb-2 mb-3 select-none">
                      <span className="font-sans text-[10px] font-bold uppercase tracking-wider text-accent-blue">
                        Select Site Scope
                      </span>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          setShowScopeSelector(false)
                        }}
                        className="font-sans text-[10px] text-mute hover:text-ink uppercase tracking-wider cursor-pointer font-bold"
                      >
                        Cancel
                      </button>
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <button
                        type="button"
                        onClick={() => {
                          setSiteId("")
                          setShowScopeSelector(false)
                        }}
                        className={cn(
                          "w-full text-left px-3 py-2 rounded-md cursor-pointer transition-colors text-charcoal hover:bg-white/[0.04] hover:text-ink flex items-center justify-between font-sans text-xs font-normal select-none border border-transparent",
                          siteId === ""
                            ? "text-accent-blue bg-accent-blue/5 border-accent-blue/30"
                            : "hover:border-hairline"
                        )}
                      >
                        <span>All sites</span>
                        {siteId === "" && <span className="size-1.5 rounded-full bg-accent-blue shrink-0" />}
                      </button>
                      {(sites.data ?? []).map((s) => (
                        <button
                          key={s.id}
                          type="button"
                          onClick={() => {
                            setSiteId(s.id)
                            setShowScopeSelector(false)
                          }}
                          className={cn(
                            "w-full text-left px-3 py-2 rounded-md cursor-pointer transition-colors text-charcoal hover:bg-white/[0.04] hover:text-ink flex items-center justify-between font-sans text-xs font-normal select-none border border-transparent",
                            siteId === s.id
                              ? "text-accent-blue bg-accent-blue/5 border-accent-blue/30"
                              : "hover:border-hairline"
                          )}
                        >
                          <span className="truncate">Only {s.name}</span>
                          {siteId === s.id && <span className="size-1.5 rounded-full bg-accent-blue shrink-0" />}
                        </button>
                      ))}
                    </div>
                  </div>

                </div>

                {formError && (
                  <p role="alert" className="text-body-sm text-accent-red">
                    {formError}
                  </p>
                )}
                <DialogFooter>
                  <Button type="submit" disabled={create.isPending}>
                    {create.isPending ? "Adding" : "Add channel"}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      </CardHeader>
      <CardContent>
        {channels.isLoading ? (
          <p className="text-body-sm text-mute">Loading channels…</p>
        ) : (channels.data ?? []).length === 0 ? (
          <p className="text-body-sm text-charcoal">
            No channels yet — alerts are only visible in the dashboard until
            you add one.
          </p>
        ) : (
          <ul className="divide-y divide-hairline">
            {(channels.data ?? []).map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-4 py-3.5">
                <div className="flex min-w-0 items-center gap-3">
                  <StatusDot state={c.is_active ? "clean" : "idle"} />
                  <div className="shrink-0 flex items-center justify-center size-8 text-ink">
                    {getChannelIcon(getChannelIconKey(c.type, c.target_hint), "size-6.5")}
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-body-sm font-medium text-ink">
                      {c.name}
                    </p>
                    <p className="text-caption text-mute flex items-center gap-1.5 mt-0.5 flex-wrap">
                      <span className="font-mono text-[9px] uppercase tracking-wider bg-surface-deep px-1.5 py-0.5 rounded border border-hairline">
                        {getChannelKindLabel(c.type, c.target_hint)}
                      </span>
                      <span>·</span>
                      <span className="truncate">{c.target_hint}</span>
                      <span>·</span>
                      <span>{siteName(c.site_id)}</span>
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={test.isPending}
                    onClick={() => test.mutate(c.id)}
                  >
                    <Send />
                    Test
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={toggle.isPending}
                    onClick={() => toggle.mutate({ id: c.id, active: !c.is_active })}
                  >
                    {c.is_active ? "Disable" : "Enable"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Delete ${c.name}`}
                    onClick={() => {
                      if (window.confirm(`Remove the channel "${c.name}"?`)) {
                        remove.mutate(c.id)
                      }
                    }}
                  >
                    <Trash2 />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

export function SettingsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === "admin"

  return (
    <div className="relative">
      {/* Ambient background glow */}
      <div className="pointer-events-none absolute top-[-100px] left-1/2 h-[350px] w-full max-w-[800px] -translate-x-1/2 rounded-full opacity-5 blur-[140px] transition-all duration-1000 bg-glow-blue" />

      <div className="relative z-10 mb-8">
        <h1 className="text-display-lg text-ink">Settings</h1>
        <p className="mt-2 text-body-md text-charcoal">
          {isAdmin
            ? "Notifications, intelligence, users, and API access. Everything here is optional — and nothing here can break a scan."
            : "Your API keys. Notification and integration settings are managed by an admin."}
        </p>
      </div>
      <div className="space-y-6">
        {/* Everyone manages their own API keys; the rest is admin scope
            (the API enforces this server-side — hiding is just UX). */}
        <ApiKeysCard />
        {isAdmin && (
          <>
            <UsersCard />
            <ChannelsCard />
            <SmtpCard />
            <TelegramCard />
            <AiCard />
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Server className="size-4 text-charcoal" />
                  Secrets at rest
                </CardTitle>
                <CardDescription>
                  SMTP passwords, service URLs, bot tokens and API keys are
                  encrypted with your instance&rsquo;s CREDENTIALS_ENCRYPTION_KEY before
                  they reach the database, and never returned by the API.{" "}
                  <Badge variant="secondary" className="align-middle">
                    Fernet / AES-128-CBC + HMAC
                  </Badge>
                </CardDescription>
              </CardHeader>
            </Card>
          </>
        )}
      </div>
    </div>
  )
}
