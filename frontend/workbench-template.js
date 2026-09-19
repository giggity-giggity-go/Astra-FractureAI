/* Workbench template kept separate to keep app.js readable. */
window.AstraFractureAI = window.AstraFractureAI || {};
window.AstraFractureAI.workbenchTemplate = String.raw`    <main class="shell">
      <nav class="workbench-subnav" aria-label="Workbench navigation">
        <el-button class="back-button" type="primary" plain size="small" aria-label="Back to demo overview" title="Back to demo overview (Esc)" @click="$emit('goto', 'home')">
          <el-icon><back /></el-icon><span>Back</span>
        </el-button>
      </nav>
      <section class="hero">
        <div><p class="eyebrow">CLINICAL IMAGING WORKSPACE</p><h1>See the image, not the noise.</h1><p class="subtitle">Three vision models provide explainable evidence; Astra combines the image and findings into clinical assistance.</p></div>
        <div class="hero-note"><span class="pulse"></span><span>All results require review by a qualified clinician</span></div>
      </section>

      <section class="workspace-grid">
        <aside class="control-column">
          <el-card class="panel" shadow="never">
            <div class="panel-heading"><div><span class="step">01</span><h2>Image Input</h2></div><span class="muted">PNG / JPEG · ≤20 MB</span></div>
            <div class="dropzone" :class="{ 'has-file': imageUrl }" role="button" tabindex="0" @click="pickFile" @keydown.enter="pickFile" @keydown.space.prevent="pickFile" @dragover.prevent @drop.prevent="dropFile">
              <img v-if="imageUrl" :src="imageUrl" alt="Uploaded X-ray preview">
              <template v-else><el-icon><upload-filled /></el-icon><strong>Drop an X-ray image</strong><span>or click to browse</span></template>
              <input ref="fileInput" type="file" accept="image/png,image/jpeg" @change="onFileChange" hidden>
            </div>
            <div v-if="fileName" class="file-row"><el-icon><picture-filled /></el-icon><span :title="fileName">{{ fileName }}</span><el-button text type="danger" @click.stop="clearImage">Remove</el-button></div>
            <el-button v-if="imageUrl" class="full-width crop-button" plain @click="openCrop"><el-icon><crop /></el-icon> Crop & Rotate</el-button>
          </el-card>

          <el-card class="panel" shadow="never">
            <div class="panel-heading"><div><span class="step">02</span><h2>Detection Parameters</h2></div><el-button text size="small" @click="resetParams">Restore defaults</el-button></div>
            <label class="field-label">Confidence threshold <b>{{ params.conf.toFixed(2) }}</b></label>
            <el-slider v-model="params.conf" :min="0.01" :max="1" :step="0.01" show-input @change="markResultsStale"></el-slider>
            <label class="field-label">IoU threshold <b>{{ params.iou.toFixed(2) }}</b></label>
            <el-slider v-model="params.iou" :min="0" :max="0.95" :step="0.01" show-input @change="markResultsStale"></el-slider>
            <label class="field-label">Inference size <b>{{ params.imgsz }} px</b></label>
            <el-select v-model="params.imgsz" class="full-width" @change="markResultsStale"><el-option v-for="size in [320, 640, 1280]" :key="size" :label="size + ' px'" :value="size"></el-option></el-select>
            <p v-if="resultsStale" class="stale-note">Parameters changed. Run detection again to refresh results.</p>
            <el-button class="detect-button" type="primary" :loading="detecting" :disabled="!imageFile" @click="runDetection"><el-icon><magic-stick /></el-icon>{{ detecting ? 'Analyzing with three models…' : 'Run fracture detection' }}</el-button>
          </el-card>
        </aside>

        <section class="viewer-column">
          <el-card class="panel viewer-panel" shadow="never">
            <div class="panel-heading viewer-heading"><div><span class="step">03</span><h2>Medical Image Viewer</h2></div><span class="zoom-label">{{ Math.round(view.zoom * 100) }}%</span></div>
            <div class="tool-strip" role="toolbar" aria-label="Image viewer tools">
              <el-button v-for="tool in tools" :key="tool.key" size="small" :type="view.tool === tool.key ? 'primary' : 'default'" :plain="view.tool !== tool.key" @click="setTool(tool.key)" :title="tool.hint">{{ tool.label }}</el-button>
              <el-button size="small" plain @click="resetView" title="Reset viewport and clear measurements"><el-icon><refresh-left /></el-icon> Reset</el-button>
            </div>
            <div class="canvas-wrap" ref="canvasWrap" @wheel.prevent="onWheel" @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="pointerUp" @pointerleave="pointerUp">
              <canvas ref="canvas" :class="['tool-' + view.tool, { dragging: view.dragging }]" aria-label="X-ray with AI detection overlays"></canvas>
              <div v-if="!imageUrl" class="empty-view"><el-icon><picture-filled /></el-icon><span>Your image will appear here</span></div>
              <div class="viewer-legend" v-if="imageUrl"><span><i class="position-dot"></i>Fracture Location</span><span><i class="range-dot"></i>Fracture Extent</span></div>
              <div class="canvas-hint" v-if="imageUrl">{{ activeToolHint }}</div>
            </div>
            <div class="viewer-controls">
              <div class="control-group"><span>Window width</span><el-slider v-model="view.window" :min="20" :max="500" :show-tooltip="false" @input="draw"></el-slider><span class="value">{{ view.window }}</span></div>
              <div class="control-group"><span>Window level</span><el-slider v-model="view.level" :min="0" :max="255" :show-tooltip="false" @input="draw"></el-slider><span class="value">{{ view.level }}</span></div>
            </div>
            <div class="measurement-row" v-if="measurement"><span>{{ measurement }}</span><el-button text size="small" @click="clearMeasurements">Clear measurement</el-button></div>
          </el-card>
        </section>
      </section>

      <section class="results-section" v-if="pipelineState !== 'idle' || errorMessage">
        <div class="section-title"><div><p class="eyebrow">MODEL OUTPUT</p><h2>Clinical Evidence</h2></div><span v-if="results" class="timing">Total time {{ formatTime(results.processing_time) }}</span></div>
        <div class="stage-track" aria-live="polite"><div v-for="stage in stages" :key="stage.key" class="stage" :class="stage.state"><span>{{ stage.state === 'done' ? '✓' : stage.number }}</span>{{ stage.label }}</div></div>
        <el-alert v-if="partialErrors.length" class="partial-warning" :title="partialErrorText" type="warning" show-icon :closable="false"></el-alert>
        <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false"></el-alert>

        <div class="result-grid" v-if="results">
          <article v-for="card in resultCards" :key="card.key" class="result-card">
            <div class="card-top"><span class="card-icon" :class="card.tone"><el-icon><component :is="card.icon" /></el-icon></span><span class="card-time">{{ formatTime(card.time) }}</span></div>
            <h3>{{ card.title }}</h3>
            <div v-if="card.items.length" class="detections">
              <div v-for="(item, index) in card.items" :key="card.key + index" class="detection-detail">
                <div class="detection-line"><span><i v-if="card.key === 'kind'" class="kind-dot" :style="{ background: kindColor(item.name) }"></i>{{ displayLabel(card.key, item) }}</span><strong>{{ formatConfidence(item.confidence) }}</strong></div>
                <el-progress :percentage="confidencePercent(item.confidence)" :show-text="false" :stroke-width="4" :color="confidenceColor(item.confidence)"></el-progress>
                <small v-if="card.key !== 'kind' && formatBox(item.box)">{{ formatBox(item.box) }}</small>
                <small v-if="card.key === 'range' && segmentCount(item)">{{ segmentCount(item) }} contour points</small>
              </div>
            </div>
            <p v-else class="no-detection">No findings above the threshold.</p>
            <p v-if="card.key === 'kind'" class="card-footnote">Type classification is not overlaid on the image</p>
          </article>
        </div>

        <article v-if="results" class="explanation-card">
          <div class="explanation-head"><div><p class="eyebrow">ASTRA CLINICAL ASSISTANT</p><h2>Clinical Assistance Report</h2></div><span class="actual-model">{{ selectedModel || 'Model pending' }}</span></div>
          <div v-if="explaining && !explanation" class="thinking-state"><i></i>The model is combining the image with YOLO evidence…</div>
          <div v-if="explanation" class="markdown" :class="{ streaming: explaining }" v-html="renderMarkdown(explanation)"></div>
          <el-button v-if="!explaining && pipelineState === 'error' && results" type="primary" plain @click="runExplanation">Retry report</el-button>
          <p class="clinical-disclaimer">This report is for screening and demonstration only; it is not a diagnosis or treatment recommendation.</p>
        </article>
      </section>
    </main>
    <el-dialog v-model="settingsOpen" title="Connection Settings" width="min(92vw, 480px)">
      <p class="dialog-help">Your browser stores only the model selection and never handles API keys.</p>
      <label class="field-label">Available LLM models</label><el-select v-model="draftSettings.model" class="full-width" :loading="health === 'checking'" placeholder="Select a model"><el-option v-for="model in availableModels" :key="model" :label="model" :value="model"></el-option></el-select>
      <template #footer><el-button @click="settingsOpen = false">Cancel</el-button><el-button type="primary" @click="saveSettings">Save & Check</el-button></template>
    </el-dialog>

    <el-dialog v-model="cropOpen" title="Crop Image" width="min(92vw, 800px)" @opened="initCropper" @closed="destroyCropper">
      <div class="crop-toolbar"><el-button @click="cropRotate(-90)">Rotate left 90°</el-button><el-button @click="cropRotate(90)">Rotate right 90°</el-button><el-button @click="cropReset">Reset crop</el-button></div>
      <div class="crop-stage"><img ref="cropImage" :src="imageUrl" alt="Crop preview"></div>
      <template #footer><el-button @click="cropOpen = false">Cancel</el-button><el-button type="primary" @click="applyCrop">Apply crop</el-button></template>
    </el-dialog>`;
