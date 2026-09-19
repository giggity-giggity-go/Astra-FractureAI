/* Astra FractureAI — no-build Vue client */
(() => {
  const { createApp, ref, reactive, computed, nextTick, onMounted, onBeforeUnmount, provide, inject, watch } = Vue;
  const icons = ElementPlusIconsVue;
  const STORAGE_KEY = 'astra-fractureai-settings';
  const MAX_FILE_BYTES = 20 * 1024 * 1024;
  const IMAGE_TYPES = new Set(['image/png', 'image/jpeg']);

  const POSITION_LABELS = {
    forearm_fracture: 'Forearm Fracture', shoulder_fracture: 'Shoulder Fracture', elbow_positive: 'Elbow Positive',
    humerus: 'Humerus', wrist_positive: 'Wrist Positive', fingers_positive: 'Fingers Positive'
  };
  const RANGE_LABELS = {
    item: 'Fracture Extent', fingers_positive: 'Fingers', shoulder_fracture: 'Shoulder', elbow_positive: 'Elbow',
    forearm_fracture: 'Forearm', humerus: 'Humerus', wrist_positive: 'Wrist'
  };
  const KIND_LABELS = {
    Comminuted: 'Comminuted Fracture', Greenstick: 'Greenstick Fracture', Healthy: 'Healthy', Linear: 'Linear Fracture',
    Oblique: 'Oblique Fracture', 'Oblique Displaced': 'Displaced Oblique Fracture', Segmental: 'Segmental Fracture',
    Spiral: 'Spiral Fracture', Transverse: 'Transverse Fracture', 'Transverse Displaced': 'Displaced Transverse Fracture'
  };
  const KIND_COLORS = {
    Comminuted: '#ff6600', Greenstick: '#ff8800', Healthy: '#39d98a', Linear: '#ffaa00',
    Oblique: '#ffcc00', 'Oblique Displaced': '#ff9900', Segmental: '#ff5500', Spiral: '#ff4400',
    Transverse: '#ff7700', 'Transverse Displaced': '#ff334d'
  };
  /* === WorkbenchView (existing workbench logic, full state) === */
  function loadSavedSettings() {
    try {
      const value = JSON.parse(localStorage.getItem('astra-fractureai-settings') || '{}');
      return value && typeof value === 'object' ? value : {};
    } catch {
      localStorage.removeItem('astra-fractureai-settings');
      return {};
    }
  }

  const WorkbenchView = {
    name: 'WorkbenchView',
    emits: ['goto'],
    template: window.AstraFractureAI.workbenchTemplate,
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
      const detectionId = ref('');
      const FIXED_MODELS = ['gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-luna', 'gpt-5.6-terra'];
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
        { key: 'window', label: 'Window / Level', hint: 'Drag vertically to adjust window width; drag horizontally to adjust window level' },
        { key: 'zoom', label: 'Zoom', hint: 'Drag vertically to zoom, or use the mouse wheel' },
        { key: 'pan', label: 'Pan', hint: 'Drag the image to pan' },
        { key: 'length', label: 'Length', hint: 'Click two image points to measure pixel distance' },
        { key: 'angle', label: 'Angle', hint: 'Click three image points to measure an angle' },
        { key: 'rotate', label: 'Rotate', hint: 'Drag horizontally to rotate the image' }
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
      const partialErrorText = computed(() => `Some vision models did not complete: ${partialErrors.value.map(error => error.model || error.name || 'Unknown model').join(', ')}. Remaining results are still available.`);
      const healthLabel = computed(() => ({ checking: 'check', healthy: 'connected', offline: 'check failed' }[health.value]));
      const healthClass = computed(() => `health-${health.value}`);
      const activeToolHint = computed(() => tools.find(tool => tool.key === view.tool)?.hint || 'Use the tool to inspect the image');
      const stages = computed(() => {
        const state = pipelineState.value;
        return [
          { key: 'image', number: '01', label: imageUrl.value ? 'Image loaded' : 'Waiting for image', state: imageUrl.value ? 'done' : 'idle' },
          { key: 'yolo', number: '02', label: state === 'detecting_yolo' ? 'Three YOLO models running in parallel' : results.value ? 'YOLO detection complete' : 'Waiting for detection', state: state === 'detecting_yolo' ? 'active' : results.value ? 'done' : 'idle' },
          { key: 'llm', number: '03', label: state === 'llm_thinking' ? 'Astra is reasoning' : state === 'llm_streaming' ? 'Streaming report' : state === 'llm_done' ? 'Clinical report complete' : state === 'error' ? 'Pipeline interrupted' : 'Waiting for report', state: ['llm_thinking', 'llm_streaming'].includes(state) ? 'active' : state === 'llm_done' ? 'done' : state === 'error' ? 'error' : 'idle' }
        ];
      });
      const resultCards = computed(() => results.value ? [
        { key: 'position', title: 'Fracture Location', icon: 'location', tone: 'violet', items: sortFindings(results.value.positions), time: results.value.position_time },
        { key: 'range', title: 'Fracture Extent', icon: 'aim', tone: 'cyan', items: sortFindings(results.value.range), time: results.value.range_time },
        { key: 'kind', title: 'Fracture Type', icon: 'data-analysis', tone: 'orange', items: sortFindings(results.value.kind), time: results.value.kind_time }
      ] : []);
      const measurement = computed(() => {
        const latest = measurements.value[measurements.value.length - 1];
        if (latest?.type === 'length') return `Length ${distance(latest.points[0], latest.points[1]).toFixed(1)} px`;
        if (latest?.type === 'angle') return `Angle ${angleDegrees(latest.points).toFixed(1)}°`;
        const needed = view.tool === 'angle' ? 3 : view.tool === 'length' ? 2 : 0;
        return needed && pendingMeasurement.value.length ? `Selected ${pendingMeasurement.value.length}/${needed} points` : '';
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
        if (!IMAGE_TYPES.has(file.type)) return 'Only PNG or JPEG images are supported.';
        if (file.size > MAX_FILE_BYTES) return 'Image must not exceed 20 MB.';
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
        nextImage.onerror = () => { errorMessage.value = 'The browser could not decode this image.'; };
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
        if (!cropped) { errorMessage.value = 'Could not create the cropped image.'; return; }
        cropped.toBlob(blob => {
          if (!blob) { errorMessage.value = 'Could not export the cropped image.'; return; }
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
          if (!response.ok || data.success === false) throw new Error(data.error || `Detection failed (HTTP ${response.status}）`);
          if (runId !== generation) return;
          results.value = data;
          detectionId.value = data.detection_id || '';
          if (!detectionId.value) throw new Error('The server did not return a detection reference.');
          pipelineState.value = 'yolo_done';
          draw();
          await runExplanation(runId);
        } catch (error) {
          if (error.name === 'AbortError' || runId !== generation) return;
          pipelineState.value = 'error';
          errorMessage.value = error.message || 'Detection failed. Check the backend connection.';
        } finally {
          if (runId === generation) activeRequest = null;
        }
      }
      async function runExplanation(existingRunId) {
        if (!detectionId.value || !results.value) return;
        let runId = existingRunId;
        if (runId === undefined) {
          cancelRequests();
          runId = generation;
          activeRequest = new AbortController();
        }
        const taskId = detectionId.value;
        detectionId.value = '';
        pipelineState.value = 'llm_thinking';
        explanation.value = '';
        actualModel.value = '';
        errorMessage.value = '';
        try {
          const response = await fetch(api('/api/explain'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: activeRequest.signal,
            body: JSON.stringify({ detection_id: taskId, stream: true })
          });
          if (!response.ok) {
            const failure = await response.json().catch(() => ({}));
            throw new Error(failure.error || `Report generation failed (HTTP ${response.status}）`);
          }
          await consumeSSE(response, runId);
        } catch (error) {
          if (error.name === 'AbortError' || runId !== generation) return;
          pipelineState.value = 'error';
          errorMessage.value = error.message || 'Clinical report generation failed.';
        }
      }
      async function consumeSSE(response, runId) {
        if (!response.body) throw new Error('This browser does not support streaming responses.');
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
            try { payload = JSON.parse(raw); } catch { throw new Error('The server returned an invalid streaming event.'); }
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
        if (!gotText) throw new Error('The model returned no displayable report content.');
        if (!completed) throw new Error('The report stream ended before its completion marker.');
        pipelineState.value = 'llm_done';
      }
      function fileToDataUrl(file) {
        return new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = () => reject(new Error('Could not read the image.'));
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
        // Simulate a 2–5 second reconnect delay so users can see the state transition
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
        const name = item?.name || String(item?.class ?? 'Unknown model');
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
      function formatBox(box) { const normalized = normalizeBox(box); return normalized ? `Box [${normalized.map(value => Math.round(value)).join(', ')}]` : ''; }
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

  window.AstraFractureAI.WorkbenchView = WorkbenchView;
})();
