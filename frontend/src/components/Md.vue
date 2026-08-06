<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps<{ content: string }>()

function escapeHtml(s: string) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

marked.setOptions({ breaks: true, gfm: true })

// 先转义 HTML 再走 Markdown：避免模型/用户内容中的原始 HTML 或脚本注入
const html = computed(() => marked.parse(escapeHtml(props.content || ''), { async: false }) as string)
</script>

<template>
  <div class="md-body" v-html="html"></div>
</template>

<style scoped>
.md-body { font-size: 13.5px; line-height: 1.65; word-break: break-word; }
.md-body :deep(h1), .md-body :deep(h2), .md-body :deep(h3),
.md-body :deep(h4), .md-body :deep(h5), .md-body :deep(h6) { margin: 10px 0 6px; font-size: 1.05em; font-weight: 600; }
.md-body :deep(p) { margin: 6px 0; }
.md-body :deep(ul), .md-body :deep(ol) { margin: 6px 0; padding-left: 20px; }
.md-body :deep(li) { margin: 2px 0; }
.md-body :deep(pre) { background: var(--video-bg); border: 1px solid var(--border); border-radius: 6px; padding: 10px; overflow-x: auto; font-size: 12px; margin: 8px 0; }
.md-body :deep(code) { background: var(--video-bg); padding: 1px 4px; border-radius: 4px; font-size: 12px; font-family: var(--font-mono); }
.md-body :deep(pre code) { background: none; padding: 0; }
.md-body :deep(table) { border-collapse: collapse; margin: 8px 0; font-size: 12.5px; display: block; overflow-x: auto; }
.md-body :deep(th), .md-body :deep(td) { border: 1px solid var(--border); padding: 5px 9px; }
.md-body :deep(th) { background: var(--video-bg); }
.md-body :deep(a) { color: var(--primary); }
.md-body :deep(blockquote) { margin: 6px 0; padding-left: 10px; border-left: 3px solid var(--border); color: var(--muted-foreground); }
.md-body :deep(hr) { border: none; border-top: 1px solid var(--border); margin: 10px 0; }
</style>
