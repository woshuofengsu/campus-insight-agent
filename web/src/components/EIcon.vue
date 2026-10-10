<script setup>
// 单色线性图标（v4 方案 §3「统一单色线性图标（替换 emoji）」）
//
// 注意（2026-10-06 修，重要）：本组件原来只用**自带的 9 个**路径，未命中一律回落成
// `PATHS.more`（"三横线+箭头"）。而全站模板里写的是 `config/icons.js` 那套名字（122 个），
// 于是**紧急求助 / 保存 / 天气 / 麦克风 / 检查 全站都画成同一个"更多"图标**——
// 431 处引用里绝大多数被静默画错。
// 之所以一直没被发现：门禁只检查"名字在 icons.js 里有"，**没人检查 EIcon 是否真的读了那张表**；
// `ui_audit`/`mobile_audit` 测的是对比度与热区，测不出"图形画错"。
// 现在改为**以 `config/icons.js` 为准**，本地这 9 个（老年端调过的形状）作为覆盖项。
import { ICON_PATHS } from '../config/icons'

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 24 },
})

// 老年端专用的 9 个：形状按"老人看得清"调过，语义与 icons.js 同名项一致 → 显式覆盖
const LOCAL_PATHS = {
  home: 'M3 10.5 12 3l9 7.5M5.5 9.5V20h13V9.5M10 20v-5h4v5',
  speak: 'M4 5h16v10H9l-5 4V5Z M8.5 9.5h7M8.5 12h4',
  list: 'M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01',
  family: 'M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM2.5 20a6.5 6.5 0 0 1 13 0M17 5.5a3 3 0 0 1 0 6M18.5 20a6.4 6.4 0 0 0-2-4.6',
  bell: 'M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6ZM10 19a2 2 0 0 0 4 0',
  more: 'M4 7h16M4 12h16M4 17h10M18 15l3 2.5-3 2.5',
  alert: 'M12 3 2 20h20L12 3ZM12 9v5M12 17h.01',
  phone: 'M8 3h8a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1ZM11 18h2',
  community: 'M3 20V9.5l6-3.5 6 3.5V20M15 20v-6h6v6M9 20v-4h4v4M3 20h18',
}

// 全量图标表在前、本地覆盖在后；未命中才回落 `more`（仍是单色线性图形，不会空白）
const PATHS = { ...ICON_PATHS, ...LOCAL_PATHS }
</script>

<template>
  <svg :width="props.size" :height="props.size" viewBox="0 0 24 24" fill="none"
       stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
       aria-hidden="true" focusable="false" style="flex:0 0 auto;vertical-align:-0.18em;">
    <path :d="PATHS[props.name] || PATHS.more" />
  </svg>
</template>
