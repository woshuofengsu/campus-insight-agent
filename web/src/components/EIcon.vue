<script setup>
// 老年端单色线性图标（v4 方案 §3「统一单色线性图标（替换 emoji）」）
//
// 为什么老年端先换这些：顶部导航在**每一个**页面上，是老人看到次数最多的图形；
// emoji 在不同手机上是不同的厂商字形（大小、配色、甚至有无都不一样），
// 而这里画的是 `stroke="currentColor"` 的线性图标：**跟着文字色走**（暗色/高对比模式自动适配）、
// 尺寸可控（`size`）、永远单色，不会出现"一行六个花里胡哨的彩色小图"。
//
// 范围说明（不夸大）：本组件目前只服务**老年端布局的标题栏与 6 个导航入口**；
// 页面正文里仍有一批 emoji（约 170 处，跨 10 个页面），全量替换会动到所有截图基线，
// 列为赛后项——台账 §7 与 dev-log 五十九节都如实写着，没有假装"全站已换"。
const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 24 },
})

// 只用 24×24 视框、线宽 2 的简单路径：老人看得清、也便于以后加图标（照抄一组即可）
const PATHS = {
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
</script>

<template>
  <svg :width="props.size" :height="props.size" viewBox="0 0 24 24" fill="none"
       stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
       aria-hidden="true" focusable="false" style="flex:0 0 auto;vertical-align:-0.18em;">
    <path :d="PATHS[props.name] || PATHS.more" />
  </svg>
</template>
