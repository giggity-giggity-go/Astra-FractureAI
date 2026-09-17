/* Astra FractureAI — no-build Vue client */
(() => {
  const { createApp, ref, reactive, computed, nextTick, onMounted, onBeforeUnmount, provide, inject, watch } = Vue;
  const icons = ElementPlusIconsVue;
  const STORAGE_KEY = 'astra-fractureai-settings';
  const MAX_FILE_BYTES = 20 * 1024 * 1024;
  const IMAGE_TYPES = new Set(['image/png', 'image/jpeg']);

  const POSITION_LABELS = {
    forearm_fracture: '前臂骨折', shoulder_fracture: '肩部骨折', elbow_positive: '肘部阳性',
    humerus: '肱骨', wrist_positive: '腕部阳性', fingers_positive: '手指阳性'
  };
  const RANGE_LABELS = {
    item: '骨折范围', fingers_positive: '手指', shoulder_fracture: '肩部', elbow_positive: '肘部',
    forearm_fracture: '前臂', humerus: '肱骨', wrist_positive: '腕部'
  };
  const KIND_LABELS = {
    Comminuted: '粉碎性骨折', Greenstick: '青枝骨折', Healthy: '健康', Linear: '线性骨折',
    Oblique: '斜形骨折', 'Oblique Displaced': '斜形移位骨折', Segmental: '节段性骨折',
    Spiral: '螺旋形骨折', Transverse: '横形骨折', 'Transverse Displaced': '横形移位骨折'
  };
  const KIND_COLORS = {
    Comminuted: '#ff6600', Greenstick: '#ff8800', Healthy: '#39d98a', Linear: '#ffaa00',
    Oblique: '#ffcc00', 'Oblique Displaced': '#ff9900', Segmental: '#ff5500', Spiral: '#ff4400',
    Transverse: '#ff7700', 'Transverse Displaced': '#ff334d'
  };

  /* === HomeView (landing page) === */
  const HomeView = {
    name: 'HomeView',
    emits: ['goto'],
    template: `
      <section class="home-page" tabindex="-1">
        <div class="home-disclaimer-banner">
          <el-icon><warning-filled /></el-icon>
          <span>Research preview · Not a medical device · For education & demonstration only</span>
          <button type="button" class="home-disclaimer-why" @click="openFullDisclaimer">Why?</button>
        </div>
        <div class="home-hero">
          <span class="home-eyebrow">FractureAI demo · Source available on GitHub</span>
          <h1 class="home-title">Faster X-ray reads,<br /><span class="home-title-accent">with reasoning.</span></h1>
          <p class="home-subtitle">AI-assisted fracture detection on X-rays with GPT-6 Astra. Images are sent to your configured backend for YOLO detection and Astra explanation.</p>
          <div class="home-cta-row">
            <el-button class="home-cta" type="primary" size="large" @click="$emit('goto', 'workbench')">
              <el-icon><magic-stick /></el-icon> Launch Demo
            </el-button>
            <a class="home-secondary-cta" href="https://github.com/giggity-giggity-go/Astra-FractureAI" target="_blank" rel="noopener noreferrer">
              View source on GitHub ↗
            </a>
          </div>
          <div class="home-health-pill" :class="healthClass">
            <span class="home-health-dot"></span>
            <span>{{ healthLabel }}</span>
          </div>
        </div>
        <div class="home-trust-strip">
          <span class="home-trust-item">Configurable LLM explanation</span>
          <span class="home-trust-divider"></span>
          <span class="home-trust-item">YOLOv8 / v9 / v11 ensemble</span>
          <span class="home-trust-divider"></span>
          <span class="home-trust-item">Configured backend + cloud inference</span>
          <span class="home-trust-divider"></span>
          <span class="home-trust-item">Source available on GitHub</span>
        </div>
        <div class="home-feature-grid">
          <article class="home-feature-card">
            <el-icon class="home-feature-icon" style="color: var(--cyan)"><aim /></el-icon>
            <h3>3-model ensemble</h3>
            <p>YOLOv8/v9/v11 run through the backend; we surface model disagreements, not hide them.</p>
          </article>
          <article class="home-feature-card">
            <el-icon class="home-feature-icon" style="color: var(--violet)"><location /></el-icon>
            <h3>Configurable model explanation</h3>
            <p>The configured model service explains detection results in plain English.</p>
          </article>
          <article class="home-feature-card">
            <el-icon class="home-feature-icon" style="color: var(--orange)"><data-analysis /></el-icon>
            <h3>Configurable inference backend</h3>
            <p>Your browser sends images to the configured backend and cloud inference services. Review your deployment before uploading sensitive data.</p>
          </article>
          <article class="home-feature-card">
            <el-icon class="home-feature-icon" style="color: var(--yellow)"><picture-filled /></el-icon>
            <h3>Source available, no signup</h3>
            <p>Source available on GitHub. Review the code and deployment before uploading images.</p>
          </article>
        </div>
        <div class="home-how-it-works">
          <h2 class="home-section-heading">How it works</h2>
          <ol class="home-steps">
            <li><span class="home-step-num">01</span><strong>Upload</strong> a sample X-ray (drag-drop or browse)</li>
            <li><span class="home-step-num">02</span><strong>Detect</strong> — the backend runs 3 YOLO models in parallel</li>
            <li><span class="home-step-num">03</span><strong>Explain</strong> — the configured model summarizes findings through the backend</li>
          </ol>
        </div>
        <div class="home-footer-cta">
          <p>Ready for your first detection?</p>
          <el-button type="primary" plain size="large" @click="$emit('goto', 'workbench')">
            Launch Demo →
          </el-button>
        </div>
        <div class="home-disclaimer-full" v-if="showFullDisclaimer">
          <h3>Full disclaimer</h3>
          <p>For research and education only. Astra-FractureAI is not a medical device and is not intended for clinical use, diagnosis, or treatment decisions. Do not upload real patient X-rays or any data containing PHI. Outputs are generated by AI and may be incorrect. Always consult a qualified radiologist.</p>
          <el-button text @click="showFullDisclaimer = false">Close</el-button>
        </div>
      </section>
    `,
    setup() {
      const showFullDisclaimer = Vue.ref(false);
      const openFullDisclaimer = () => { showFullDisclaimer.value = true; };
      const health = Vue.inject('appHealth', Vue.ref('checking'));
      const healthLabel = Vue.computed(() => ({ checking: 'Checking API…', healthy: 'API connected', offline: 'API unavailable' }[health.value]));
      const healthClass = Vue.computed(() => `health-${health.value}`);
      return { showFullDisclaimer, openFullDisclaimer, healthLabel, healthClass };
    }
  };

  function loadSavedSettings() {
    try {
      const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      return value && typeof value === 'object' ? value : {};
    } catch {
      localStorage.removeItem(STORAGE_KEY);
      return {};
    }
  }

  /* === WorkbenchView (existing workbench logic, full state) === */
  const WorkbenchView = {
    name: 'WorkbenchView',
    emits: ['goto'],
    template: '    <main class="shell">\n      <section class="hero">\n        <div><p class="eyebrow">CLINICAL IMAGING WORKSPACE</p><h1>看清影像，而非噪声。</h1><p class="subtitle">三路视觉模型提供可解释证据，Astra 将影像与检测结果汇总为辅助临床建议。</p></div>\n        <div class="hero-note"><span class="pulse"></span><span>所有结果须由专业医生复核</span></div>\n      </section>\n\n      <section class="workspace-grid">\n        <aside class="control-column">\n          <el-card class="panel" shadow="never">\n            <div class="panel-heading"><div><span class="step">01</span><h2>影像输入</h2></div><el-button text size="small" @click="$emit(\'goto\', \'home\')">Home</el-button><span class="muted">PNG / JPEG · ≤20 MB</span></div>\n            <div class="dropzone" :class="{ \'has-file\': imageUrl }" role="button" tabindex="0" @click="pickFile" @keydown.enter="pickFile" @keydown.space.prevent="pickFile" @dragover.prevent @drop.prevent="dropFile">\n              <img v-if="imageUrl" :src="imageUrl" alt="已上传的 X 光片预览">\n              <template v-else><el-icon><upload-filled /></el-icon><strong>拖入 X 光片</strong><span>或点击选择文件</span></template>\n              <input ref="fileInput" type="file" accept="image/png,image/jpeg" @change="onFileChange" hidden>\n            </div>\n            <div v-if="fileName" class="file-row"><el-icon><picture-filled /></el-icon><span :title="fileName">{{ fileName }}</span><el-button text type="danger" @click.stop="clearImage">移除</el-button></div>\n            <el-button v-if="imageUrl" class="full-width crop-button" plain @click="openCrop"><el-icon><crop /></el-icon> 裁剪与旋转</el-button>\n          </el-card>\n\n          <el-card class="panel" shadow="never">\n            <div class="panel-heading"><div><span class="step">02</span><h2>检测参数</h2></div><el-button text size="small" @click="resetParams">恢复默认</el-button></div>\n            <label class="field-label">置信度阈值 <b>{{ params.conf.toFixed(2) }}</b></label>\n            <el-slider v-model="params.conf" :min="0.01" :max="1" :step="0.01" show-input @change="markResultsStale"></el-slider>\n            <label class="field-label">IoU 阈值 <b>{{ params.iou.toFixed(2) }}</b></label>\n            <el-slider v-model="params.iou" :min="0" :max="0.95" :step="0.01" show-input @change="markResultsStale"></el-slider>\n            <label class="field-label">推理尺寸 <b>{{ params.imgsz }} px</b></label>\n            <el-select v-model="params.imgsz" class="full-width" @change="markResultsStale"><el-option v-for="size in [320, 640, 1280]" :key="size" :label="size + \' px\'" :value="size"></el-option></el-select>\n            <p v-if="resultsStale" class="stale-note">参数已变化，请重新检测以更新结果。</p>\n            <el-button class="detect-button" type="primary" :loading="detecting" :disabled="!imageFile" @click="runDetection"><el-icon><magic-stick /></el-icon>{{ detecting ? \'三模型分析中…\' : \'开始骨折检测\' }}</el-button>\n          </el-card>\n        </aside>\n\n        <section class="viewer-column">\n          <el-card class="panel viewer-panel" shadow="never">\n            <div class="panel-heading viewer-heading"><div><span class="step">03</span><h2>医学影像查看器</h2></div><span class="zoom-label">{{ Math.round(view.zoom * 100) }}%</span></div>\n            <div class="tool-strip" role="toolbar" aria-label="影像查看工具">\n              <el-button v-for="tool in tools" :key="tool.key" size="small" :type="view.tool === tool.key ? \'primary\' : \'default\'" :plain="view.tool !== tool.key" @click="setTool(tool.key)" :title="tool.hint">{{ tool.label }}</el-button>\n              <el-button size="small" plain @click="resetView" title="恢复原始视口并清除测量"><el-icon><refresh-left /></el-icon> 重置</el-button>\n            </div>\n            <div class="canvas-wrap" ref="canvasWrap" @wheel.prevent="onWheel" @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="pointerUp" @pointerleave="pointerUp">\n              <canvas ref="canvas" :class="[\'tool-\' + view.tool, { dragging: view.dragging }]" aria-label="X 光片与 AI 检测叠加层"></canvas>\n              <div v-if="!imageUrl" class="empty-view"><el-icon><picture-filled /></el-icon><span>影像将在此处显示</span></div>\n              <div class="viewer-legend" v-if="imageUrl"><span><i class="position-dot"></i>骨折位置</span><span><i class="range-dot"></i>骨折范围</span></div>\n              <div class="canvas-hint" v-if="imageUrl">{{ activeToolHint }}</div>\n            </div>\n            <div class="viewer-controls">\n              <div class="control-group"><span>窗宽</span><el-slider v-model="view.window" :min="20" :max="500" :show-tooltip="false" @input="draw"></el-slider><span class="value">{{ view.window }}</span></div>\n              <div class="control-group"><span>窗位</span><el-slider v-model="view.level" :min="0" :max="255" :show-tooltip="false" @input="draw"></el-slider><span class="value">{{ view.level }}</span></div>\n            </div>\n            <div class="measurement-row" v-if="measurement"><span>{{ measurement }}</span><el-button text size="small" @click="clearMeasurements">清除测量</el-button></div>\n          </el-card>\n        </section>\n      </section>\n\n      <section class="results-section" v-if="pipelineState !== \'idle\' || errorMessage">\n        <div class="section-title"><div><p class="eyebrow">MODEL OUTPUT</p><h2>临床证据</h2></div><span v-if="results" class="timing">总耗时 {{ formatTime(results.processing_time) }}</span></div>\n        <div class="stage-track" aria-live="polite"><div v-for="stage in stages" :key="stage.key" class="stage" :class="stage.state"><span>{{ stage.state === \'done\' ? \'✓\' : stage.number }}</span>{{ stage.label }}</div></div>\n        <el-alert v-if="partialErrors.length" class="partial-warning" :title="partialErrorText" type="warning" show-icon :closable="false"></el-alert>\n        <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false"></el-alert>\n\n        <div class="result-grid" v-if="results">\n          <article v-for="card in resultCards" :key="card.key" class="result-card">\n            <div class="card-top"><span class="card-icon" :class="card.tone"><el-icon><component :is="card.icon" /></el-icon></span><span class="card-time">{{ formatTime(card.time) }}</span></div>\n            <h3>{{ card.title }}</h3>\n            <div v-if="card.items.length" class="detections">\n              <div v-for="(item, index) in card.items" :key="card.key + index" class="detection-detail">\n                <div class="detection-line"><span><i v-if="card.key === \'kind\'" class="kind-dot" :style="{ background: kindColor(item.name) }"></i>{{ displayLabel(card.key, item) }}</span><strong>{{ formatConfidence(item.confidence) }}</strong></div>\n                <el-progress :percentage="confidencePercent(item.confidence)" :show-text="false" :stroke-width="4" :color="confidenceColor(item.confidence)"></el-progress>\n                <small v-if="card.key !== \'kind\' && formatBox(item.box)">{{ formatBox(item.box) }}</small>\n                <small v-if="card.key === \'range\' && segmentCount(item)">{{ segmentCount(item) }} 个轮廓点</small>\n              </div>\n            </div>\n            <p v-else class="no-detection">阈值以上未发现结果。</p>\n            <p v-if="card.key === \'kind\'" class="card-footnote">类型分类不叠加至影像</p>\n          </article>\n        </div>\n\n        <article v-if="results" class="explanation-card">\n          <div class="explanation-head"><div><p class="eyebrow">ASTRA CLINICAL ASSISTANT</p><h2>辅助评估报告</h2></div><span class="actual-model">{{ selectedModel || \'等待模型\' }}</span></div>\n          <div v-if="explaining && !explanation" class="thinking-state"><i></i>模型正在综合影像与 YOLO 证据…</div>\n          <div v-if="explanation" class="markdown" :class="{ streaming: explaining }" v-html="renderMarkdown(explanation)"></div>\n          <el-button v-if="!explaining && pipelineState === \'error\' && results" type="primary" plain @click="runExplanation">重试生成报告</el-button>\n          <p class="clinical-disclaimer">本报告仅用于辅助筛查与演示，不构成诊断或治疗意见。</p>\n        </article>\n      </section>\n    </main>\n    <el-dialog v-model="settingsOpen" title="连接设置" width="min(92vw, 480px)">\n      <p class="dialog-help">浏览器只保存模型选择，不接触任何 API 密钥。</p>\n      <label class="field-label">可用 LLM 模型</label><el-select v-model="draftSettings.model" class="full-width" :loading="health === \'checking\'" placeholder="选择模型"><el-option v-for="model in availableModels" :key="model" :label="model" :value="model"></el-option></el-select>\n      <template #footer><el-button @click="settingsOpen = false">取消</el-button><el-button type="primary" @click="saveSettings">保存并检查</el-button></template>\n    </el-dialog>\n\n    <el-dialog v-model="cropOpen" title="裁剪影像" width="min(92vw, 800px)" @opened="initCropper" @closed="destroyCropper">\n      <div class="crop-toolbar"><el-button @click="cropRotate(-90)">左转 90°</el-button><el-button @click="cropRotate(90)">右转 90°</el-button><el-button @click="cropReset">重置裁剪</el-button></div>\n      <div class="crop-stage"><img ref="cropImage" :src="imageUrl" alt="裁剪预览"></div>\n      <template #footer><el-button @click="cropOpen = false">取消</el-button><el-button type="primary" @click="applyCrop">应用裁剪</el-button></template>\n    </el-dialog>',
    setup(_props, { expose }) {
      const canvas = ref(null);
      const canvasWrap = ref(null);
      const fileInput = ref(null);
      const cropImage = ref(null);
      const imageFile = ref(null);
      const imageUrl = ref('');
      const fileName = ref('');
      const results = ref(null);
      const resultsStale = ref(false);
      const explanation = ref('');
      const actualModel = ref('');
      const FIXED_MODELS = ['gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-luna'];
      const availableModels = ref(FIXED_MODELS);
      const health = ref('checking');
      // Mirror local health to the root-level shared ref so HomeView's pill stays in sync.
      const setAppHealth = inject('setAppHealth', null);
      watch(health, (val) => { if (setAppHealth) setAppHealth(val); });
      const settingsOpen = ref(false);
      const cropOpen = ref(false);
      const errorMessage = ref('');
      const pipelineState = ref('idle');
      const measurements = ref([]);
      const pendingMeasurement = ref([]);

      const saved = loadSavedSettings();
      const settings = reactive({ model: saved.llmModel || '' });
      const draftSettings = reactive({ model: settings.model });
      const params = reactive({ conf: 0.25, iou: 0.70, imgsz: 640 });
      const view = reactive({
        zoom: 1, panX: 0, panY: 0, rotation: 0, window: 220, level: 128,
        tool: 'pan', dragging: false
      });

      const tools = [
        { key: 'window', label: '窗宽/窗位', hint: '上下拖动调整窗宽，左右拖动调整窗位' },
        { key: 'zoom', label: '缩放', hint: '上下拖动缩放，也可使用滚轮' },
        { key: 'pan', label: '平移', hint: '拖动影像平移' },
        { key: 'length', label: '长度', hint: '依次点击两个影像点测量像素距离' },
        { key: 'angle', label: '角度', hint: '依次点击三个影像点测量夹角' },
        { key: 'rotate', label: '旋转', hint: '左右拖动自由旋转影像' }
      ];

      let sourceImage = null;
      let cropper = null;
      let resizeObserver = null;
      let activeRequest = null;
      let generation = 0;
      let dragStart = null;
      let viewAtDragStart = null;

      const api = path => path;
      const selectedModel = computed(() => settings.model);
      const setAppSelectedModel = inject('setAppSelectedModel', null);
      watch(selectedModel, (model) => { if (setAppSelectedModel) setAppSelectedModel(model); }, { immediate: true });
      const detecting = computed(() => pipelineState.value === 'detecting_yolo');
      const explaining = computed(() => ['llm_thinking', 'llm_streaming'].includes(pipelineState.value));
      const partialErrors = computed(() => Array.isArray(results.value?.errors) ? results.value.errors : []);
      const partialErrorText = computed(() => `部分视觉模型未完成：${partialErrors.value.map(error => error.model || error.name || '未知模型').join('、')}。其余结果仍可使用。`);
      const healthLabel = computed(() => ({ checking: '正在检查 API', healthy: 'API 已连接', offline: 'API 不可用' }[health.value]));
      const healthClass = computed(() => `health-${health.value}`);
      const activeToolHint = computed(() => tools.find(tool => tool.key === view.tool)?.hint || '使用工具检查影像');
      const stages = computed(() => {
        const state = pipelineState.value;
        return [
          { key: 'image', number: '01', label: imageUrl.value ? '影像已载入' : '等待影像', state: imageUrl.value ? 'done' : 'idle' },
          { key: 'yolo', number: '02', label: state === 'detecting_yolo' ? '三路 YOLO 并行检测' : results.value ? 'YOLO 检测完成' : '等待检测', state: state === 'detecting_yolo' ? 'active' : results.value ? 'done' : 'idle' },
          { key: 'llm', number: '03', label: state === 'llm_thinking' ? 'Astra 正在思考' : state === 'llm_streaming' ? '报告流式生成中' : state === 'llm_done' ? '辅助报告完成' : state === 'error' ? '流程中断' : '等待报告', state: ['llm_thinking', 'llm_streaming'].includes(state) ? 'active' : state === 'llm_done' ? 'done' : state === 'error' ? 'error' : 'idle' }
        ];
      });
      const resultCards = computed(() => results.value ? [
        { key: 'position', title: '骨折位置', icon: 'location', tone: 'violet', items: sortFindings(results.value.positions), time: results.value.position_time },
        { key: 'range', title: '骨折范围', icon: 'aim', tone: 'cyan', items: sortFindings(results.value.range), time: results.value.range_time },
        { key: 'kind', title: '骨折类型', icon: 'data-analysis', tone: 'orange', items: sortFindings(results.value.kind), time: results.value.kind_time }
      ] : []);
      const measurement = computed(() => {
        const latest = measurements.value[measurements.value.length - 1];
        if (latest?.type === 'length') return `长度 ${distance(latest.points[0], latest.points[1]).toFixed(1)} px`;
        if (latest?.type === 'angle') return `角度 ${angleDegrees(latest.points).toFixed(1)}°`;
        const needed = view.tool === 'angle' ? 3 : view.tool === 'length' ? 2 : 0;
        return needed && pendingMeasurement.value.length ? `已选 ${pendingMeasurement.value.length}/${needed} 点` : '';
      });

      function sortFindings(items) {
        return [...(Array.isArray(items) ? items : [])].sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0));
      }

      function pickFile() { fileInput.value?.click(); }
      function onFileChange(event) {
        const file = event.target.files?.[0];
        if (file) setFile(file);
        event.target.value = '';
      }
      function dropFile(event) {
        const file = event.dataTransfer?.files?.[0];
        if (file) setFile(file);
      }
      function validateFile(file) {
        if (!IMAGE_TYPES.has(file.type)) return '仅支持 PNG 或 JPEG 影像。';
        if (file.size > MAX_FILE_BYTES) return '影像不能超过 20 MB。';
        return '';
      }
      function setFile(file) {
        const invalid = validateFile(file);
        if (invalid) { errorMessage.value = invalid; return; }
        cancelRequests();
        revokeImageUrl();
        imageFile.value = file;
        fileName.value = file.name;
        imageUrl.value = URL.createObjectURL(file);
        results.value = null;
        resultsStale.value = false;
        explanation.value = '';
        actualModel.value = '';
        errorMessage.value = '';
        pipelineState.value = 'idle';
        resetView();
        loadImage(imageUrl.value);
      }
      function clearImage() {
        cancelRequests();
        revokeImageUrl();
        imageFile.value = null;
        imageUrl.value = '';
        fileName.value = '';
        sourceImage = null;
        results.value = null;
        explanation.value = '';
        actualModel.value = '';
        pipelineState.value = 'idle';
        resetView();
      }
      function revokeImageUrl() {
        if (imageUrl.value) URL.revokeObjectURL(imageUrl.value);
      }
      function loadImage(src) {
        const nextImage = new Image();
        nextImage.onload = () => {
          if (nextImage.src !== src) return;
          sourceImage = nextImage;
          nextTick(draw);
        };
        nextImage.onerror = () => { errorMessage.value = '浏览器无法解码此影像。'; };
        nextImage.src = src;
      }

      function openCrop() { cropOpen.value = true; }
      function initCropper() {
        destroyCropper();
        if (cropImage.value) cropper = new Cropper(cropImage.value, { viewMode: 1, background: false, autoCropArea: 0.92, responsive: true });
      }
      function destroyCropper() { cropper?.destroy(); cropper = null; }
      function cropRotate(degrees) { cropper?.rotate(degrees); }
      function cropReset() { cropper?.reset(); }
      function applyCrop() {
        if (!cropper) return;
        const cropped = cropper.getCroppedCanvas({ maxWidth: 4096, maxHeight: 4096, imageSmoothingEnabled: true, imageSmoothingQuality: 'high' });
        if (!cropped) { errorMessage.value = '无法生成裁剪影像。'; return; }
        cropped.toBlob(blob => {
          if (!blob) { errorMessage.value = '无法导出裁剪影像。'; return; }
          const base = fileName.value.replace(/\.[^.]+$/, '') || 'radiograph';
          cropOpen.value = false;
          setFile(new File([blob], `${base}-crop.jpg`, { type: 'image/jpeg' }));
        }, 'image/jpeg', 0.94);
      }

      function resizeCanvas() {
        const element = canvas.value;
        const bounds = canvasWrap.value?.getBoundingClientRect();
        if (!element || !bounds || !bounds.width || !bounds.height) return false;
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const width = Math.round(bounds.width * dpr);
        const height = Math.round(bounds.height * dpr);
        if (element.width !== width || element.height !== height) {
          element.width = width;
          element.height = height;
          element.style.width = `${bounds.width}px`;
          element.style.height = `${bounds.height}px`;
        }
        return true;
      }
      function viewportTransform() {
        const element = canvas.value;
        if (!sourceImage || !element) return null;
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const cssWidth = element.width / dpr;
        const cssHeight = element.height / dpr;
        const baseScale = Math.min(cssWidth / sourceImage.naturalWidth, cssHeight / sourceImage.naturalHeight);
        return { dpr, cssWidth, cssHeight, scale: baseScale * view.zoom, centerX: cssWidth / 2 + view.panX, centerY: cssHeight / 2 + view.panY, radians: view.rotation * Math.PI / 180 };
      }
      function imageToViewport(point, transform = viewportTransform()) {
        if (!transform || !sourceImage) return { x: 0, y: 0 };
        const dx = (point.x - sourceImage.naturalWidth / 2) * transform.scale;
        const dy = (point.y - sourceImage.naturalHeight / 2) * transform.scale;
        const cos = Math.cos(transform.radians), sin = Math.sin(transform.radians);
        return { x: transform.centerX + dx * cos - dy * sin, y: transform.centerY + dx * sin + dy * cos };
      }
      function viewportToImage(point, transform = viewportTransform()) {
        if (!transform || !sourceImage) return null;
        const dx = point.x - transform.centerX, dy = point.y - transform.centerY;
        const cos = Math.cos(-transform.radians), sin = Math.sin(-transform.radians);
        const x = (dx * cos - dy * sin) / transform.scale + sourceImage.naturalWidth / 2;
        const y = (dx * sin + dy * cos) / transform.scale + sourceImage.naturalHeight / 2;
        return { x: Math.max(0, Math.min(sourceImage.naturalWidth, x)), y: Math.max(0, Math.min(sourceImage.naturalHeight, y)) };
      }
      function eventPoint(event) {
        const bounds = canvas.value.getBoundingClientRect();
        return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
      }
      function detectionScale() {
        const size = results.value?.image_size;
        return {
          x: sourceImage && Number(size?.width) > 0 ? sourceImage.naturalWidth / Number(size.width) : 1,
          y: sourceImage && Number(size?.height) > 0 ? sourceImage.naturalHeight / Number(size.height) : 1
        };
      }
      function normalizeBox(box) {
        if (!box) return null;
        const sx = detectionScale().x, sy = detectionScale().y;
        if (Array.isArray(box) && box.length >= 4) {
          const [x1, y1, third, fourth] = box.map(Number);
          const x2 = third > x1 ? third : x1 + third;
          const y2 = fourth > y1 ? fourth : y1 + fourth;
          return [x1 * sx, y1 * sy, x2 * sx, y2 * sy];
        }
        if ([box.x1, box.y1, box.x2, box.y2].every(Number.isFinite)) return [box.x1 * sx, box.y1 * sy, box.x2 * sx, box.y2 * sy];
        if ([box.x, box.y, box.width, box.height].every(Number.isFinite)) return [box.x * sx, box.y * sy, (box.x + box.width) * sx, (box.y + box.height) * sy];
        return null;
      }
      function normalizeSegments(segments) {
        const sx = detectionScale().x, sy = detectionScale().y;
        if (segments && Array.isArray(segments.x) && Array.isArray(segments.y) && segments.x.length === segments.y.length && segments.x.length >= 3) {
          return segments.x.map((x, index) => ({ x: Number(x) * sx, y: Number(segments.y[index]) * sy })).filter(point => Number.isFinite(point.x) && Number.isFinite(point.y));
        }
        if (Array.isArray(segments) && segments.length >= 3) {
          if (Array.isArray(segments[0])) return segments.map(pair => ({ x: Number(pair[0]) * sx, y: Number(pair[1]) * sy })).filter(point => Number.isFinite(point.x) && Number.isFinite(point.y));
          const points = [];
          for (let index = 0; index + 1 < segments.length; index += 2) points.push({ x: Number(segments[index]) * sx, y: Number(segments[index + 1]) * sy });
          return points.filter(point => Number.isFinite(point.x) && Number.isFinite(point.y));
        }
        return [];
      }

      function draw() {
        if (!resizeCanvas()) return;
        const element = canvas.value;
        const context = element.getContext('2d');
        const transform = viewportTransform();
        context.setTransform(1, 0, 0, 1, 0, 0);
        context.clearRect(0, 0, element.width, element.height);
        if (!sourceImage || !transform) return;
        context.setTransform(transform.dpr, 0, 0, transform.dpr, 0, 0);
        context.save();
        context.translate(transform.centerX, transform.centerY);
        context.rotate(transform.radians);
        context.scale(transform.scale, transform.scale);
        context.filter = `contrast(${Math.max(0.2, 220 / view.window)}) brightness(${Math.max(0.2, 1 + (view.level - 128) / 255)})`;
        context.drawImage(sourceImage, -sourceImage.naturalWidth / 2, -sourceImage.naturalHeight / 2);
        context.restore();
        context.filter = 'none';
        drawDetectionGroup(context, results.value?.positions, '#ffe45c', 'position', transform);
        drawDetectionGroup(context, results.value?.range, '#56d6f4', 'range', transform);
        drawMeasurements(context, transform);
      }
      function drawDetectionGroup(context, items, color, type, transform) {
        sortFindings(items).forEach(item => {
          const polygon = normalizeSegments(item.segments || item.polygon || item.points);
          if (polygon.length >= 3) {
            context.beginPath();
            polygon.forEach((point, index) => { const projected = imageToViewport(point, transform); index ? context.lineTo(projected.x, projected.y) : context.moveTo(projected.x, projected.y); });
            context.closePath();
            context.fillStyle = `${color}28`;
            context.strokeStyle = color;
            context.lineWidth = 2;
            context.fill();
            context.stroke();
          }
          const box = normalizeBox(item.box);
          if (!box) return;
          const corners = [{ x: box[0], y: box[1] }, { x: box[2], y: box[1] }, { x: box[2], y: box[3] }, { x: box[0], y: box[3] }].map(point => imageToViewport(point, transform));
          context.beginPath();
          corners.forEach((point, index) => index ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y));
          context.closePath();
          context.strokeStyle = color;
          context.lineWidth = 2.5;
          context.stroke();
          drawDetectionLabel(context, `${displayLabel(type, item)} ${formatConfidence(item.confidence)}`, corners[0], color);
        });
      }
      function drawDetectionLabel(context, text, anchor, color) {
        context.save();
        context.font = '600 12px system-ui, sans-serif';
        const width = context.measureText(text).width + 12;
        const y = Math.max(2, anchor.y - 22);
        context.fillStyle = 'rgba(5,10,15,.88)';
        context.fillRect(anchor.x, y, width, 20);
        context.fillStyle = color;
        context.fillText(text, anchor.x + 6, y + 14);
        context.restore();
      }
      function drawMeasurements(context, transform) {
        [...measurements.value, ...(pendingMeasurement.value.length ? [{ type: view.tool, points: pendingMeasurement.value }] : [])].forEach(entry => {
          const projected = entry.points.map(point => imageToViewport(point, transform));
          if (!projected.length) return;
          context.save();
          context.strokeStyle = '#ffae70';
          context.fillStyle = '#ffae70';
          context.lineWidth = 2;
          context.setLineDash([6, 4]);
          context.beginPath();
          projected.forEach((point, index) => index ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y));
          context.stroke();
          context.setLineDash([]);
          projected.forEach(point => { context.beginPath(); context.arc(point.x, point.y, 4, 0, Math.PI * 2); context.fill(); });
          if (entry.type === 'length' && entry.points.length === 2) drawDetectionLabel(context, `${distance(...entry.points).toFixed(1)} px`, projected[1], '#ffae70');
          if (entry.type === 'angle' && entry.points.length === 3) drawDetectionLabel(context, `${angleDegrees(entry.points).toFixed(1)}°`, projected[1], '#ffae70');
          context.restore();
        });
      }

      function setTool(tool) {
        view.tool = tool;
        pendingMeasurement.value = [];
        draw();
      }
      function pointerDown(event) {
        if (!sourceImage) return;
        const point = eventPoint(event);
        if (['length', 'angle'].includes(view.tool)) {
          const imagePoint = viewportToImage(point);
          if (!imagePoint) return;
          const needed = view.tool === 'angle' ? 3 : 2;
          pendingMeasurement.value = [...pendingMeasurement.value, imagePoint];
          if (pendingMeasurement.value.length === needed) {
            measurements.value = [...measurements.value, { type: view.tool, points: pendingMeasurement.value }];
            pendingMeasurement.value = [];
          }
          draw();
          return;
        }
        view.dragging = true;
        dragStart = point;
        viewAtDragStart = { panX: view.panX, panY: view.panY, zoom: view.zoom, rotation: view.rotation, window: view.window, level: view.level };
        canvas.value.setPointerCapture?.(event.pointerId);
      }
      function pointerMove(event) {
        if (!view.dragging || !dragStart || !viewAtDragStart) return;
        const point = eventPoint(event), dx = point.x - dragStart.x, dy = point.y - dragStart.y;
        if (view.tool === 'pan') { view.panX = viewAtDragStart.panX + dx; view.panY = viewAtDragStart.panY + dy; }
        if (view.tool === 'zoom') view.zoom = clamp(viewAtDragStart.zoom * Math.exp(-dy / 180), 0.1, 10);
        if (view.tool === 'rotate') view.rotation = viewAtDragStart.rotation + dx * 0.6;
        if (view.tool === 'window') { view.level = Math.round(clamp(viewAtDragStart.level + dx, 0, 255)); view.window = Math.round(clamp(viewAtDragStart.window - dy * 2, 20, 500)); }
        draw();
      }
      function pointerUp(event) {
        if (view.dragging) canvas.value?.releasePointerCapture?.(event.pointerId);
        view.dragging = false;
        dragStart = null;
        viewAtDragStart = null;
      }
      function onWheel(event) {
        if (!sourceImage) return;
        const before = viewportToImage(eventPoint(event));
        view.zoom = clamp(view.zoom * (event.deltaY > 0 ? 0.9 : 1.1), 0.1, 10);
        const after = before ? imageToViewport(before) : null;
        if (after) { const target = eventPoint(event); view.panX += target.x - after.x; view.panY += target.y - after.y; }
        draw();
      }
      function resetView() {
        Object.assign(view, { zoom: 1, panX: 0, panY: 0, rotation: 0, window: 220, level: 128, tool: 'pan', dragging: false });
        clearMeasurements();
        nextTick(draw);
      }
      function clearMeasurements() { measurements.value = []; pendingMeasurement.value = []; draw(); }
      function resetParams() { Object.assign(params, { conf: 0.25, iou: 0.70, imgsz: 640 }); markResultsStale(); }
      function markResultsStale() { if (results.value) resultsStale.value = true; }

      function cancelRequests() {
        generation += 1;
        activeRequest?.abort();
        activeRequest = null;
      }
      async function runDetection() {
        if (!imageFile.value) return;
        cancelRequests();
        const runId = generation;
        activeRequest = new AbortController();
        pipelineState.value = 'detecting_yolo';
        errorMessage.value = '';
        results.value = null;
        resultsStale.value = false;
        explanation.value = '';
        actualModel.value = '';
        try {
          const body = new FormData();
          body.append('file', imageFile.value, imageFile.value.name);
          body.append('conf', String(params.conf));
          body.append('iou', String(params.iou));
          body.append('imgsz', String(params.imgsz));
          const response = await fetch(api('/api/detect'), { method: 'POST', body, signal: activeRequest.signal });
          const data = await response.json().catch(() => ({}));
          if (!response.ok || data.success === false) throw new Error(data.error || `检测失败（HTTP ${response.status}）`);
          if (runId !== generation) return;
          results.value = data;
          pipelineState.value = 'yolo_done';
          draw();
          await runExplanation(runId);
        } catch (error) {
          if (error.name === 'AbortError' || runId !== generation) return;
          pipelineState.value = 'error';
          errorMessage.value = error.message || '检测失败，请检查后端连接。';
        } finally {
          if (runId === generation) activeRequest = null;
        }
      }
      async function runExplanation(existingRunId) {
        if (!imageFile.value || !results.value) return;
        let runId = existingRunId;
        if (runId === undefined) {
          cancelRequests();
          runId = generation;
          activeRequest = new AbortController();
        }
        pipelineState.value = 'llm_thinking';
        explanation.value = '';
        actualModel.value = '';
        errorMessage.value = '';
        try {
          const imageBase64 = await fileToDataUrl(imageFile.value);
          if (runId !== generation) return;
          const response = await fetch(api('/api/explain'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: activeRequest.signal,
            body: JSON.stringify({ image_base64: imageBase64, yolo_result: results.value, stream: true })
          });
          if (!response.ok) {
            const failure = await response.json().catch(() => ({}));
            throw new Error(failure.error || `报告生成失败（HTTP ${response.status}）`);
          }
          await consumeSSE(response, runId);
        } catch (error) {
          if (error.name === 'AbortError' || runId !== generation) return;
          pipelineState.value = 'error';
          errorMessage.value = error.message || '辅助报告生成失败。';
        }
      }
      async function consumeSSE(response, runId) {
        if (!response.body) throw new Error('当前浏览器不支持流式响应。');
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let gotText = false;
        let completed = false;
        while (true) {
          const { value, done } = await reader.read();
          if (runId !== generation) { await reader.cancel(); return; }
          buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
          const events = buffer.split(/\r?\n\r?\n/);
          buffer = done ? '' : events.pop();
          for (const event of events) {
            const dataLines = event.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, ''));
            if (!dataLines.length) continue;
            const raw = dataLines.join('\n').trim();
            if (raw === '[DONE]') { completed = true; break; }
            let payload;
            try { payload = JSON.parse(raw); } catch { throw new Error('服务端返回了无效的流式事件。'); }
            if (payload.error) throw new Error(payload.error);
            if (payload.model) actualModel.value = payload.model;
            if (payload.text) {
              explanation.value += payload.text;
              gotText = true;
              pipelineState.value = 'llm_streaming';
            }
          }
          if (completed || done) break;
        }
        if (!gotText) throw new Error('模型未返回可显示的报告内容。');
        if (!completed) throw new Error('报告流在完成标记前中断。');
        pipelineState.value = 'llm_done';
      }
      function fileToDataUrl(file) {
        return new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = () => reject(new Error('无法读取影像。'));
          reader.readAsDataURL(file);
        });
      }

      function openSettings() {
        draftSettings.model = settings.model;
        settingsOpen.value = true;
        runHealthCheck();
      }
      function saveSettings() {
        settings.model = availableModels.value.includes(draftSettings.model) ? draftSettings.model : (availableModels.value[0] || '');
        draftSettings.model = settings.model;
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ llmModel: settings.model }));
        settingsOpen.value = false;
        runHealthCheck();
      }
      async function runHealthCheck() {
        health.value = 'checking';
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000);
        // 模拟 2-5 秒的"重新连接"延迟,让用户看到状态切换
        const delay = 2000 + Math.floor(Math.random() * 3000);
        const delayPromise = new Promise(resolve => setTimeout(resolve, delay));
        try {
          const [response] = await Promise.all([
            fetch('/api/health', { signal: controller.signal }),
            delayPromise
          ]);
          clearTimeout(timeoutId);
          if (!response.ok) throw new Error('health failed');
          health.value = 'healthy';
        } catch {
          clearTimeout(timeoutId);
          health.value = 'offline';
        }
      }

      function renderMarkdown(text) {
        const html = window.marked.parse(text || '', { gfm: true, breaks: true });
        return window.DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
      }
      function displayLabel(type, item) {
        const name = item?.name || String(item?.class ?? '未知');
        if (type === 'position') return POSITION_LABELS[name] || name;
        if (type === 'range') return RANGE_LABELS[name] || name;
        if (type === 'kind') return `${KIND_LABELS[name] || name}${KIND_LABELS[name] ? ` · ${name}` : ''}`;
        return name;
      }
      function confidencePercent(value) { return Math.round(clamp(Number(value) * 100 || 0, 0, 100)); }
      function formatConfidence(value) { return `${confidencePercent(value)}%`; }
      function confidenceColor(value) { const percent = confidencePercent(value); return percent < 60 ? '#ff7885' : percent < 80 ? '#f0bd58' : '#65e3a1'; }
      function kindColor(name) { return KIND_COLORS[name] || '#ffae70'; }
      function formatTime(value) { const number = Number(value); return Number.isFinite(number) ? `${number.toFixed(number < 10 ? 2 : 0)} ms` : '—'; }
      function formatBox(box) { const normalized = normalizeBox(box); return normalized ? `框 [${normalized.map(value => Math.round(value)).join(', ')}]` : ''; }
      function segmentCount(item) { const points = normalizeSegments(item?.segments || item?.polygon || item?.points); return points.length; }
      function clamp(value, minimum, maximum) { return Math.min(maximum, Math.max(minimum, value)); }
      function distance(a, b) { return Math.hypot(b.x - a.x, b.y - a.y); }
      function angleDegrees(points) {
        if (!points || points.length < 3) return 0;
        const [a, b, c] = points;
        const ab = { x: a.x - b.x, y: a.y - b.y }, cb = { x: c.x - b.x, y: c.y - b.y };
        const denominator = Math.hypot(ab.x, ab.y) * Math.hypot(cb.x, cb.y);
        if (!denominator) return 0;
        return Math.acos(clamp((ab.x * cb.x + ab.y * cb.y) / denominator, -1, 1)) * 180 / Math.PI;
      }

      onMounted(() => {
        runHealthCheck();
        resizeObserver = new ResizeObserver(() => draw());
        if (canvasWrap.value) resizeObserver.observe(canvasWrap.value);
      });
      expose({ openSettings });

      onBeforeUnmount(() => {
        cancelRequests();
        destroyCropper();
        resizeObserver?.disconnect();
        revokeImageUrl();
      });

      return {
        canvas, canvasWrap, fileInput, cropImage, imageFile, imageUrl, fileName, results, resultsStale,
        explanation, actualModel, availableModels, health, healthLabel, healthClass, settingsOpen, cropOpen,
        draftSettings, params, view, tools, activeToolHint, pipelineState, detecting, explaining, errorMessage,
        stages, resultCards, partialErrors, partialErrorText, measurement, selectedModel,
        pickFile, onFileChange, dropFile, clearImage, openCrop, initCropper, destroyCropper, cropRotate,
        cropReset, applyCrop, resetParams, markResultsStale, draw, setTool, pointerDown, pointerMove, pointerUp,
        onWheel, resetView, clearMeasurements, runDetection, runExplanation, openSettings, saveSettings, runHealthCheck,
        renderMarkdown, displayLabel, confidencePercent, formatConfidence, confidenceColor, kindColor,
        formatTime, formatBox, segmentCount, icons
      };
    }
  };

  /* === Root app (router + topbar shared state) === */
  const rootApp = createApp({

    setup() {
      const currentView = ref('home');   // 'home' | 'workbench'
      const goto = (name) => { currentView.value = name; };
      const workbench = ref(null);
      const openSettings = () => { if (currentView.value !== 'workbench') goto('workbench'); nextTick(() => workbench.value?.openSettings()); };
      const hasOpenElementPlusDialog = () => Array.from(document.querySelectorAll('.el-overlay')).some((overlay) => {
        const dialog = overlay.querySelector('.el-dialog');
        if (!dialog) return false;
        const style = window.getComputedStyle(overlay);
        return style.display !== 'none' && style.visibility !== 'hidden';
      });
      const handleGlobalKey = (event) => {
        if (event.key === 'Escape' && currentView.value === 'workbench' &&
            !event.target?.closest?.('input, textarea, select, [contenteditable]') &&
            !event.target?.isContentEditable && !hasOpenElementPlusDialog()) {
          event.preventDefault();
          goto('home');
        }
      };
      // Shared health state: WorkbenchView mutates via this ref, HomeView reads via inject.
      const sharedHealth = ref('checking');
      const healthLabel = computed(() => ({ checking: 'Checking API…', healthy: 'API connected', offline: 'API unavailable' }[sharedHealth.value]));
      const healthClass = computed(() => `health-${sharedHealth.value}`);
      provide('appHealth', sharedHealth);
      // Expose sharedHealth so WorkbenchView can read it (it has its own ref but we keep them in sync below).
      // WorkbenchView will continue to own its own `health` ref; we mirror it via watch in onMounted.
      // Simpler: register a global setter that WorkbenchView will call after its health ref updates.
      const setHealth = (val) => { sharedHealth.value = val; };
      provide('setAppHealth', setHealth);
      const sharedModel = ref(loadSavedSettings().llmModel || '');
      provide('appSelectedModel', sharedModel);
      provide('setAppSelectedModel', (model) => { sharedModel.value = model; });
      onMounted(() => { document.addEventListener('keydown', handleGlobalKey); });
      onBeforeUnmount(() => { document.removeEventListener('keydown', handleGlobalKey); });
      return { currentView, goto, workbench, openSettings, healthLabel, healthClass, selectedModel: sharedModel };
    }
  });
  rootApp
    .component('home-view', HomeView)
    .component('workbench-view', WorkbenchView)
    .use(ElementPlus)
    .component('setting', icons.Setting)
    .component('upload-filled', icons.UploadFilled)
    .component('picture-filled', icons.PictureFilled)
    .component('crop', icons.Crop)
    .component('magic-stick', icons.MagicStick)
    .component('refresh-left', icons.RefreshLeft)
    .component('aim', icons.Aim)
    .component('location', icons.Location)
    .component('data-analysis', icons.DataAnalysis)
    .component('warning-filled', icons.WarningFilled)
    .mount('#app');
})();
