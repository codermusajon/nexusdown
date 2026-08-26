/**
 * Downloader Application Core Client Logic
 */

document.addEventListener('DOMContentLoaded', () => {
  // Global modal helpers
  window.openModal = function(id) {
    const modal = document.getElementById(id);
    if (modal) modal.style.display = 'flex';
  };

  window.closeModal = function(id) {
    const modal = document.getElementById(id);
    if (modal) modal.style.display = 'none';
  };

  function updateSearchQuotaPill(quota) {
    if (!quota) return;
    const badge = document.getElementById('searchLimitBadge');
    const text = document.getElementById('searchLimitText');
    if (badge && text) {
      if (quota.is_premium) {
        text.textContent = '👑 PREMIUM CHEKSIZ';
        badge.style.borderColor = 'rgba(245, 158, 11, 0.6)';
        badge.style.color = '#f59e0b';
      } else {
        const maxStr = quota.max_searches !== null ? quota.max_searches : '∞';
        text.textContent = `Qidiruv: ${quota.searches_today}/${maxStr}`;
      }
    }
  }

  // Fetch current user auth me status and update search limit pill
  async function checkAuthStatus() {
    try {
      const res = await fetch('/api/auth/me/');
      const data = await res.json();
      if (data.quota) {
        updateSearchQuotaPill(data.quota);
      }
    } catch (e) {}
  }
  checkAuthStatus();

  // Elements
  const navTabs = document.querySelectorAll('.nav-tab-btn');
  const tabPanes = document.querySelectorAll('.tab-pane');
  
  const mediaUrlInput = document.getElementById('mediaUrlInput');
  const btnInspect = document.getElementById('btnInspect');
  const mediaPreviewCard = document.getElementById('mediaPreviewCard');
  
  const mediaThumbnail = document.getElementById('mediaThumbnail');
  const mediaVideoPlayer = document.getElementById('mediaVideoPlayer');
  const btnPlayMediaVideo = document.getElementById('btnPlayMediaVideo');
  const mediaDuration = document.getElementById('mediaDuration');
  const mediaTitle = document.getElementById('mediaTitle');
  const mediaAuthor = document.getElementById('mediaAuthor');
  const formatOptionsGrid = document.getElementById('formatOptionsGrid');
  const btnTriggerDownload = document.getElementById('btnTriggerDownload');

  const DEFAULT_PLACEHOLDER_SVG = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 320 180"><rect width="320" height="180" fill="%230f172a"/><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="%2300f2fe" font-family="sans-serif" font-weight="bold" font-size="16">NexusDown Media</text></svg>';

  if (mediaThumbnail) {
    mediaThumbnail.onerror = () => {
      mediaThumbnail.src = DEFAULT_PLACEHOLDER_SVG;
    };
  }

  if (btnPlayMediaVideo && mediaVideoPlayer && mediaThumbnail) {
    btnPlayMediaVideo.addEventListener('click', () => {
      if (mediaVideoPlayer.src) {
        mediaThumbnail.style.display = 'none';
        btnPlayMediaVideo.style.display = 'none';
        mediaVideoPlayer.style.display = 'block';
        mediaVideoPlayer.play().catch(e => console.log('Autoplay blocked:', e));
      }
    });
  }
  
  const directUrlInput = document.getElementById('directUrlInput');
  const btnDirectDownload = document.getElementById('btnDirectDownload');
  
  const imageFileInput = document.getElementById('imageFileInput');
  const dropzone = document.getElementById('dropzone');
  const targetFormatSelect = document.getElementById('targetFormatSelect');
  const btnConvertImages = document.getElementById('btnConvertImages');
  const selectedFilesList = document.getElementById('selectedFilesList');
  
  const historyTableBody = document.getElementById('historyTableBody');
  const btnRefreshHistory = document.getElementById('btnRefreshHistory');

  let currentInspectedData = null;
  let selectedFormatId = null;
  let selectedMediaType = 'video';
  let selectedFiles = [];

  // Tab Switcher
  navTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      navTabs.forEach(t => t.classList.remove('active'));
      tabPanes.forEach(p => p.style.display = 'none');
      
      tab.classList.add('active');
      const targetId = tab.getAttribute('data-tab');
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.style.display = 'block';
    });
  });

  function resetInspectionState() {
    currentInspectedData = null;
    selectedFormatId = null;
    if (mediaPreviewCard) mediaPreviewCard.style.display = 'none';
    if (photoGallerySection) photoGallerySection.style.display = 'none';
    if (photoGalleryGrid) photoGalleryGrid.innerHTML = '';
    if (formatOptionsGrid) formatOptionsGrid.innerHTML = '';
    if (directLinkContainer) directLinkContainer.style.display = 'none';
    if (directLinkInput) directLinkInput.value = '';
    if (mediaTitle) mediaTitle.textContent = '';
    if (mediaAuthor) mediaAuthor.textContent = '';
    if (mediaDuration) mediaDuration.textContent = '00:00';
    if (mediaVideoPlayer) {
      mediaVideoPlayer.pause();
      mediaVideoPlayer.src = '';
      mediaVideoPlayer.style.display = 'none';
    }
    if (btnPlayMediaVideo) btnPlayMediaVideo.style.display = 'none';
    if (mediaThumbnail) {
      mediaThumbnail.style.display = 'block';
      mediaThumbnail.src = '';
    }
  }

  // Unique Internet User Identifier Management
  function getOrCreateUserId() {
    let userId = localStorage.getItem('user_unique_id');
    if (!userId) {
      userId = 'usr_' + Date.now().toString(36) + '_' + Math.random().toString(36).substring(2, 11);
      localStorage.setItem('user_unique_id', userId);
    }
    document.cookie = `user_unique_id=${userId}; path=/; max-age=315360000; SameSite=Lax`;
    return userId;
  }

  // Initial load
  getOrCreateUserId();
  refreshHistory();

  // URL Inspector (Media / Video / Audio)
  if (btnInspect) {
    btnInspect.addEventListener('click', async () => {
      const url = mediaUrlInput ? mediaUrlInput.value.trim() : '';
      if (!url) {
        showToast('Iltimos, manzilni kiriting.', 'error');
        return;
      }

      resetInspectionState();
      setLoading(btnInspect, true, 'Tekshirilmoqda...');

      try {
        const response = await fetch('/api/inspect/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
            'X-User-Id': getOrCreateUserId()
          },
          body: JSON.stringify({ url })
        });

        const data = await response.json();

        if (!response.ok) {
          resetInspectionState();
          if (data.error_code === 'UNREGISTERED_LIMIT_REACHED') {
            openModal('modalUnregisteredLimit');
          } else if (data.error_code === 'REGISTERED_LIMIT_REACHED') {
            openModal('modalRegisteredLimit');
          } else {
            showToast(data.error || 'Manzil bo\'yicha media topilmadi.', 'error');
          }
          return;
        }

        if (data.error || data.status === 'error' || (!data.video_formats?.length && !data.audio_url && !data.fallback_url)) {
          resetInspectionState();
          showToast(data.error || 'Manzil bo\'yicha media topilmadi.', 'error');
          return;
        }

        if (data.quota_info) {
          updateSearchQuotaPill(data.quota_info);
        }

        currentInspectedData = data;
        renderMediaInspection(data);
        showToast('Media linklari topildi!', 'success');
        refreshHistory();


      } catch (err) {
        resetInspectionState();
        showToast('Server bilan bog\'lanishda xatolik yuz berdi.', 'error');
      } finally {
        setLoading(btnInspect, false, 'Chiqazish');
      }
    });
  }

  const directLinkContainer = document.getElementById('directLinkContainer');
  const directLinkInput = document.getElementById('directLinkInput');
  const btnCopyDirectLink = document.getElementById('btnCopyDirectLink');
  const btnOpenDirectLink = document.getElementById('btnOpenDirectLink');
  const selectedFormatLabel = document.getElementById('selectedFormatLabel');

  function updateDirectLink(url, label) {
    if (!url) return;
    if (directLinkInput) directLinkInput.value = url;
    if (btnOpenDirectLink) btnOpenDirectLink.href = url;
    if (selectedFormatLabel) selectedFormatLabel.textContent = label || '';
    if (directLinkContainer) directLinkContainer.style.display = 'block';
  }

  if (btnCopyDirectLink) {
    btnCopyDirectLink.addEventListener('click', () => {
      if (directLinkInput && directLinkInput.value) {
        navigator.clipboard.writeText(directLinkInput.value);
        showToast('Direct download link copied!', 'success');
      }
    });
  }

  const photoGallerySection = document.getElementById('photoGallerySection');
  const photoGalleryGrid = document.getElementById('photoGalleryGrid');
  const photoGalleryCount = document.getElementById('photoGalleryCount');

  // Render Inspected Media Details & Direct Stream Links
  function renderMediaInspection(data) {
    if (mediaTitle) mediaTitle.textContent = data.title;
    if (mediaAuthor) mediaAuthor.textContent = `Uploaded by ${data.uploader}`;
    if (mediaDuration) mediaDuration.textContent = data.duration_str;
    if (mediaThumbnail) mediaThumbnail.src = data.thumbnail || 'https://via.placeholder.com/320x180?text=No+Thumbnail';
    
    if (formatOptionsGrid) formatOptionsGrid.innerHTML = '';
    selectedFormatId = null;

    if (photoGalleryGrid) photoGalleryGrid.innerHTML = '';
    const photoFormats = (data.video_formats || []).filter(f => f.format_id.startsWith('photo_') || f.ext === 'jpg');

    // If photos are found, render visual Photo Gallery Grid
    if (photoFormats.length > 0 && photoGallerySection && photoGalleryGrid) {
      if (photoGalleryCount) photoGalleryCount.textContent = photoFormats.length;
      
      photoFormats.forEach((fmt, idx) => {
        const photoCard = document.createElement('div');
        photoCard.className = 'photo-card';
        photoCard.innerHTML = `
          <div class="photo-card-img-wrapper">
            <img src="${escapeHtml(fmt.download_url)}" alt="${escapeHtml(fmt.label)}" class="photo-card-img" loading="lazy">
          </div>
          <div class="photo-card-meta">
            <span style="font-weight: 600; color: var(--text-primary);">${escapeHtml(fmt.label)}</span>
            <span class="photo-card-badge">HQ JPG</span>
          </div>
          <div class="photo-card-actions">
            <button class="btn-photo-action btn-photo-copy" data-url="${escapeHtml(fmt.download_url)}">
              📋 Linkni copy
            </button>
            <a href="${escapeHtml(fmt.download_url)}" target="_blank" rel="noopener noreferrer" download class="btn-photo-action btn-photo-open">
              ⬇ Ochish
            </a>
          </div>
        `;

        // Copy button event listener inside card
        const copyBtn = photoCard.querySelector('.btn-photo-copy');
        if (copyBtn) {
          copyBtn.addEventListener('click', () => {
            navigator.clipboard.writeText(fmt.download_url);
            showToast(`${fmt.label} linki nusxalandi!`, 'success');
          });
        }

        photoGalleryGrid.appendChild(photoCard);
      });

      photoGallerySection.style.display = 'block';
    } else if (photoGallerySection) {
      photoGallerySection.style.display = 'none';
    }

    // Render Format Buttons Grid (for video format choices & audio)
    if (data.video_formats && data.video_formats.length > 0 && formatOptionsGrid) {
      let firstUnlockedSelected = false;

      data.video_formats.forEach((fmt, index) => {
        const btn = document.createElement('button');
        const isLocked = !!fmt.is_locked;

        btn.className = `format-option-btn ${isLocked ? 'locked' : ''}`;
        if (isLocked) {
          btn.innerHTML = `<span style="color:#f59e0b; font-weight:700;">👑 PRO</span> ${escapeHtml(fmt.resolution || 'High Res')} 🔒`;
        } else {
          btn.textContent = fmt.label + (fmt.filesize_mb ? ` (~${fmt.filesize_mb} MB)` : '');
        }

        btn.setAttribute('data-id', fmt.format_id);
        btn.setAttribute('data-type', fmt.format_id.startsWith('photo_') ? 'image' : 'video');

        const applySelection = () => {
          if (isLocked) {
            openModal('modalPremiumResolution');
            return;
          }

          document.querySelectorAll('.format-option-btn').forEach(b => b.classList.remove('selected'));
          btn.classList.add('selected');
          selectedFormatId = fmt.format_id;
          const isPhoto = (fmt.ext === 'jpg' || fmt.format_id.startsWith('photo_'));
          selectedMediaType = isPhoto ? 'image' : 'video';

          if (mediaVideoPlayer) {
            mediaVideoPlayer.pause();
            mediaVideoPlayer.style.display = 'none';
          }
          if (mediaThumbnail) {
            mediaThumbnail.style.display = 'block';
            mediaThumbnail.style.opacity = '0.3';
          }

          const targetUrl = fmt.download_url || data.thumbnail || data.fallback_url;

          if (isPhoto) {
            if (mediaThumbnail) mediaThumbnail.src = targetUrl || DEFAULT_PLACEHOLDER_SVG;
            if (btnPlayMediaVideo) btnPlayMediaVideo.style.display = 'none';
            if (mediaDuration) mediaDuration.style.display = 'none';
          } else {
            if (mediaThumbnail) mediaThumbnail.src = data.thumbnail || DEFAULT_PLACEHOLDER_SVG;
            if (mediaVideoPlayer && targetUrl) {
              mediaVideoPlayer.src = targetUrl;
              if (btnPlayMediaVideo) btnPlayMediaVideo.style.display = 'flex';
            }
            if (mediaDuration) {
              mediaDuration.style.display = 'block';
              mediaDuration.textContent = data.duration_str || '00:00';
            }
          }

          setTimeout(() => { if (mediaThumbnail) mediaThumbnail.style.opacity = '1'; }, 150);
          updateDirectLink(targetUrl, fmt.label);
        };

        btn.addEventListener('click', applySelection);

        if (!firstUnlockedSelected && !isLocked) {
          firstUnlockedSelected = true;
          applySelection();
        }

        formatOptionsGrid.appendChild(btn);
      });
    }


    // Render Audio Stream Link Option
    if ((data.audio_url || data.fallback_url) && formatOptionsGrid) {
      const audioBtn = document.createElement('button');
      audioBtn.className = 'format-option-btn';
      audioBtn.textContent = '🎵 Audio Stream';
      audioBtn.setAttribute('data-id', 'bestaudio/best');
      audioBtn.setAttribute('data-type', 'audio');

      audioBtn.addEventListener('click', () => {
        document.querySelectorAll('.format-option-btn').forEach(b => b.classList.remove('selected'));
        audioBtn.classList.add('selected');
        selectedFormatId = 'bestaudio/best';
        selectedMediaType = 'audio';

        const audioUrl = data.audio_url || data.fallback_url;

        if (mediaVideoPlayer) {
          mediaVideoPlayer.pause();
          mediaVideoPlayer.style.display = 'none';
          if (audioUrl) mediaVideoPlayer.src = audioUrl;
        }

        if (mediaThumbnail) {
          mediaThumbnail.style.display = 'block';
          mediaThumbnail.src = data.thumbnail || DEFAULT_PLACEHOLDER_SVG;
          mediaThumbnail.style.opacity = '1';
        }

        if (btnPlayMediaVideo && audioUrl) {
          btnPlayMediaVideo.style.display = 'flex';
          btnPlayMediaVideo.title = "Audioni eshitish";
        }

        if (mediaDuration) {
          mediaDuration.style.display = 'block';
          mediaDuration.textContent = data.duration_str || '00:00';
        }

        updateDirectLink(audioUrl, 'Audio Stream');
      });

      formatOptionsGrid.appendChild(audioBtn);
    }

    if (!data.video_formats || data.video_formats.length === 0) {
      updateDirectLink(data.audio_url || data.fallback_url, 'Direct Media Stream');
    }

    if (mediaPreviewCard) mediaPreviewCard.style.display = 'block';
  }

  // Drag & Drop Converter
  // --- Enhanced Image to PDF Converter Controller ---
  const converterManagerSection = document.getElementById('converterManagerSection');
  const imageCardsGrid = document.getElementById('imageCardsGrid');
  const imageCardsCount = document.getElementById('imageCardsCount');

  const pageSizeSelect = document.getElementById('pageSizeSelect');
  const marginSelect = document.getElementById('marginSelect');
  const qualitySelect = document.getElementById('qualitySelect');
  const outputModeSelect = document.getElementById('outputModeSelect');
  const chkPageNumbers = document.getElementById('chkPageNumbers');
  const orientationInput = document.getElementById('orientationInput');
  const orientationToggleGroup = document.getElementById('orientationToggleGroup');

  const btnAddMoreImages = document.getElementById('btnAddMoreImages');
  const btnRotateAllImages = document.getElementById('btnRotateAllImages');
  const btnSortByName = document.getElementById('btnSortByName');
  const btnClearAllImages = document.getElementById('btnClearAllImages');
  const btnConvertText = document.getElementById('btnConvertText');

  let converterImages = []; // List of { id, file, rotation, previewUrl }
  let draggedCardIdx = null;

  // Toggle PDF specific option fields visibility based on target format
  function updateConverterOptionsVisibility() {
    const isPdf = (targetFormatSelect ? targetFormatSelect.value : 'pdf') === 'pdf';
    document.querySelectorAll('.pdf-only-option').forEach(el => {
      el.style.display = isPdf ? 'flex' : 'none';
    });

    if (btnConvertText) {
      const count = converterImages.length;
      if (isPdf) {
        btnConvertText.textContent = count > 0 ? `Single PDF ga o'tkazish (${count} ta rasm)` : "PDF ga O'tkazish va Yuklab Olish";
      } else {
        const fmtName = (targetFormatSelect ? targetFormatSelect.value : 'png').toUpperCase();
        btnConvertText.textContent = count > 0 ? `${fmtName} formatiga o'tkazish (${count} ta rasm)` : `${fmtName} ga O'tkazish`;
      }
    }
  }

  if (targetFormatSelect) {
    targetFormatSelect.addEventListener('change', updateConverterOptionsVisibility);
  }

  // Orientation Toggle Group listener
  if (orientationToggleGroup) {
    orientationToggleGroup.addEventListener('click', (e) => {
      const pill = e.target.closest('.btn-toggle-pill');
      if (!pill) return;
      orientationToggleGroup.querySelectorAll('.btn-toggle-pill').forEach(b => b.classList.remove('active'));
      pill.classList.add('active');
      if (orientationInput) orientationInput.value = pill.getAttribute('data-ori') || 'auto';
    });
  }

  // File Dropzone & Picker handlers
  if (dropzone) {
    dropzone.addEventListener('click', (e) => {
      if (e.target.closest('.btn-manager-act') || e.target.closest('.image-card')) return;
      if (imageFileInput) imageFileInput.click();
    });

    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));

    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      if (e.dataTransfer.files.length) {
        appendImageFiles(e.dataTransfer.files);
      }
    });
  }

  if (imageFileInput) {
    imageFileInput.addEventListener('change', () => {
      if (imageFileInput.files.length) {
        appendImageFiles(imageFileInput.files);
        imageFileInput.value = ''; // Reset input so same files can be re-selected if needed
      }
    });
  }

  if (btnAddMoreImages) {
    btnAddMoreImages.addEventListener('click', () => imageFileInput && imageFileInput.click());
  }

  function appendImageFiles(files) {
    const validFiles = Array.from(files).filter(f => f.type.startsWith('image/'));
    if (!validFiles.length) {
      showToast('Faqat rasm fayllarini (PNG, JPG, WEBP) yuklang.', 'error');
      return;
    }

    validFiles.forEach(file => {
      const previewUrl = URL.createObjectURL(file);
      converterImages.push({
        id: 'img_' + Math.random().toString(36).substring(2, 9),
        file: file,
        rotation: 0,
        previewUrl: previewUrl
      });
    });

    renderConverterGrid();
    showToast(`${validFiles.length} ta rasm qo'shildi!`, 'success');
  }

  function renderConverterGrid() {
    if (!imageCardsGrid) return;
    imageCardsGrid.innerHTML = '';

    const count = converterImages.length;
    if (imageCardsCount) imageCardsCount.textContent = count;

    if (count === 0) {
      if (converterManagerSection) converterManagerSection.style.display = 'none';
      if (btnConvertImages) btnConvertImages.style.display = 'none';
      updateConverterOptionsVisibility();
      return;
    }

    if (converterManagerSection) converterManagerSection.style.display = 'block';
    if (btnConvertImages) btnConvertImages.style.display = 'inline-flex';
    updateConverterOptionsVisibility();

    converterImages.forEach((item, index) => {
      const card = document.createElement('div');
      card.className = 'image-card';
      card.setAttribute('draggable', 'true');
      card.setAttribute('data-index', index);

      card.innerHTML = `
        <div class="image-card-page-badge">#${index + 1}</div>
        <div class="image-card-thumb-wrapper">
          <img src="${escapeHtml(item.previewUrl)}" alt="${escapeHtml(item.file.name)}" class="image-card-thumb" style="transform: rotate(${item.rotation}deg);">
        </div>
        <div class="image-card-info">
          <span class="image-card-name" title="${escapeHtml(item.file.name)}">${escapeHtml(item.file.name)}</span>
          <span class="image-card-meta-text">${roundMB(item.file.size)} MB • ${item.rotation}°</span>
        </div>
        <div class="image-card-actions">
          <button type="button" class="btn-card-act btn-rot-ccw" title="Chaqqa burish (-90°)">↺</button>
          <button type="button" class="btn-card-act btn-rot-cw" title="O'ngga burish (+90°)">↻</button>
          <button type="button" class="btn-card-act btn-move-prev" title="Oldinga surish" ${index === 0 ? 'disabled style="opacity:0.3; cursor:default;"' : ''}>◄</button>
          <button type="button" class="btn-card-act btn-move-next" title="Orqaga surish" ${index === count - 1 ? 'disabled style="opacity:0.3; cursor:default;"' : ''}>►</button>
          <button type="button" class="btn-card-act btn-del-card" title="O'chirish">🗑️</button>
        </div>
      `;

      // Event listeners inside card
      card.querySelector('.btn-rot-ccw').addEventListener('click', (e) => {
        e.stopPropagation();
        item.rotation = (item.rotation - 90 + 360) % 360;
        renderConverterGrid();
      });

      card.querySelector('.btn-rot-cw').addEventListener('click', (e) => {
        e.stopPropagation();
        item.rotation = (item.rotation + 90) % 360;
        renderConverterGrid();
      });

      card.querySelector('.btn-move-prev').addEventListener('click', (e) => {
        e.stopPropagation();
        if (index > 0) {
          const temp = converterImages[index];
          converterImages[index] = converterImages[index - 1];
          converterImages[index - 1] = temp;
          renderConverterGrid();
        }
      });

      card.querySelector('.btn-move-next').addEventListener('click', (e) => {
        e.stopPropagation();
        if (index < converterImages.length - 1) {
          const temp = converterImages[index];
          converterImages[index] = converterImages[index + 1];
          converterImages[index + 1] = temp;
          renderConverterGrid();
        }
      });

      card.querySelector('.btn-del-card').addEventListener('click', (e) => {
        e.stopPropagation();
        URL.revokeObjectURL(item.previewUrl);
        converterImages.splice(index, 1);
        renderConverterGrid();
        showToast('Rasm o\'chirildi.', 'info');
      });

      // HTML5 Drag & Drop Reordering
      card.addEventListener('dragstart', (e) => {
        draggedCardIdx = index;
        card.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
      });

      card.addEventListener('dragend', () => {
        card.classList.remove('dragging');
        draggedCardIdx = null;
      });

      card.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
      });

      card.addEventListener('drop', (e) => {
        e.preventDefault();
        if (draggedCardIdx !== null && draggedCardIdx !== index) {
          const draggedItem = converterImages.splice(draggedCardIdx, 1)[0];
          converterImages.splice(index, 0, draggedItem);
          renderConverterGrid();
        }
      });

      imageCardsGrid.appendChild(card);
    });
  }

  // Manager Toolbar Actions
  if (btnRotateAllImages) {
    btnRotateAllImages.addEventListener('click', () => {
      converterImages.forEach(img => {
        img.rotation = (img.rotation + 90) % 360;
      });
      renderConverterGrid();
      showToast('Barcha rasmlar 90° buraldi!', 'info');
    });
  }

  if (btnSortByName) {
    btnSortByName.addEventListener('click', () => {
      converterImages.sort((a, b) => a.file.name.localeCompare(b.file.name));
      renderConverterGrid();
      showToast('Rasmlar nomi bo\'yicha tartiblandi.', 'info');
    });
  }

  if (btnClearAllImages) {
    btnClearAllImages.addEventListener('click', () => {
      if (!converterImages.length) return;
      if (confirm('Barcha yuklangan rasmlarni tozalashni tasdiqlaysizmi?')) {
        converterImages.forEach(img => URL.revokeObjectURL(img.previewUrl));
        converterImages = [];
        renderConverterGrid();
        showToast('Rasmlar ro\'yxati tozalandi.', 'info');
      }
    });
  }

  // Convert & Download Handler
  if (btnConvertImages) {
    btnConvertImages.addEventListener('click', async () => {
      if (!converterImages.length) {
        showToast('Iltimos, avval rasmlarni yuklang.', 'error');
        return;
      }

      const formData = new FormData();

      // Append files in their custom reordered sequence
      converterImages.forEach(item => formData.append('images', item.file));

      // Append rotations list
      const rotations = converterImages.map(item => item.rotation);
      formData.append('rotations', JSON.stringify(rotations));

      // Append form options
      formData.append('target_format', targetFormatSelect ? targetFormatSelect.value : 'pdf');
      formData.append('page_size', pageSizeSelect ? pageSizeSelect.value : 'a4');
      formData.append('orientation', orientationInput ? orientationInput.value : 'auto');
      formData.append('margin', marginSelect ? marginSelect.value : '0');
      formData.append('quality', qualitySelect ? qualitySelect.value : '90');
      formData.append('output_mode', outputModeSelect ? outputModeSelect.value : 'single_pdf');
      formData.append('page_numbers', (chkPageNumbers && chkPageNumbers.checked) ? 'true' : 'false');

      setLoading(btnConvertImages, true, 'Hujjat Tayyorlanmoqda...');

      try {
        const response = await fetch('/api/convert-images/', {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCookie('csrftoken'),
            'X-User-Id': getOrCreateUserId()
          },
          body: formData
        });

        const data = await response.json();

        if (!response.ok || data.error) {
          showToast(data.error || 'Konvertatsiya qilishda xatolik yuz berdi.', 'error');
          setLoading(btnConvertImages, false, 'Formatga O\'tkazish va Yuklab Olish');
          return;
        }

        showToast('Hujjat muvaffaqiyatli tayyorlandi!', 'success');

        // Trigger automatic file download
        if (data.download_url) {
          const downloadLink = document.createElement('a');
          downloadLink.href = data.download_url;
          downloadLink.download = data.title || 'converted_document.pdf';
          document.body.appendChild(downloadLink);
          downloadLink.click();
          downloadLink.remove();
        }

        refreshHistory();

      } catch (err) {
        showToast('Server bilan bog\'lanishda xatolik yuz berdi.', 'error');
      } finally {
        setLoading(btnConvertImages, false, 'Formatga O\'tkazish va Yuklab Olish');
        updateConverterOptionsVisibility();
      }
    });
  }


  // Clipboard Paste Buttons Handler (Mobile & Desktop)
  const btnPasteMediaUrl = document.getElementById('btnPasteMediaUrl');
  const btnPasteDirectUrl = document.getElementById('btnPasteDirectUrl');

  async function handleClipboardPaste(targetInput) {
    if (!targetInput) return;
    try {
      if (navigator.clipboard && navigator.clipboard.readText) {
        const text = await navigator.clipboard.readText();
        if (text && text.trim()) {
          targetInput.value = text.trim();
          showToast('Link vaqtincha xotiradan qo\'yildi!', 'success');
          targetInput.focus();
        } else {
          showToast('Xotirada matnli link topilmadi.', 'info');
        }
      } else {
        targetInput.focus();
        showToast('Iltimos, linkni qo\'lda bosing va Paste qiling.', 'info');
      }
    } catch (err) {
      targetInput.focus();
      showToast('Clipboardga kirish rad etildi. Linkni joylashtirish uchun maydonni bosing.', 'info');
    }
  }

  if (btnPasteMediaUrl && mediaUrlInput) {
    btnPasteMediaUrl.addEventListener('click', () => handleClipboardPaste(mediaUrlInput));
  }

  if (btnPasteDirectUrl && directUrlInput) {
    btnPasteDirectUrl.addEventListener('click', () => handleClipboardPaste(directUrlInput));
  }

  // Clear History Handler
  const btnClearHistory = document.getElementById('btnClearHistory');
  if (btnClearHistory) {
    btnClearHistory.addEventListener('click', async () => {
      if (!confirm("Tarixni barcha elementlarini o'chirishni tasdiqlaysizmi?")) return;
      try {
        const userId = getOrCreateUserId();
        const res = await fetch('/api/history/clear/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
            'X-User-Id': userId
          }
        });
        const data = await res.json();
        if (data.status === 'success') {
          showToast('Tarix muvaffaqiyatli tozalandi!', 'success');
          refreshHistory();
        } else {
          showToast(data.error || 'Tarixni tozalashda xatolik yuz berdi.', 'error');
        }
      } catch (err) {
        showToast('Server bilan bog\'lanishda xatolik.', 'error');
      }
    });
  }

  // Row Delete Click Event Delegation
  if (historyTableBody) {
    historyTableBody.addEventListener('click', async (e) => {
      const deleteBtn = e.target.closest('.btn-delete-row');
      if (!deleteBtn) return;
      
      const recordId = deleteBtn.getAttribute('data-id');
      if (!recordId) return;

      try {
        const userId = getOrCreateUserId();
        const res = await fetch('/api/history/delete/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
            'X-User-Id': userId
          },
          body: JSON.stringify({ id: recordId })
        });
        const data = await res.json();
        if (data.status === 'success') {
          showToast('Element muvaffaqiyatli o\'chirildi.', 'success');
          refreshHistory();
        } else {
          showToast(data.error || 'O\'chirishda xatolik yuz berdi.', 'error');
        }
      } catch (err) {
        showToast('Server bilan bog\'lanishda xatolik.', 'error');
      }
    });
  }

  // Refresh History
  if (btnRefreshHistory) {
    btnRefreshHistory.addEventListener('click', refreshHistory);
  }

  async function refreshHistory() {
    try {
      const userId = getOrCreateUserId();
      const res = await fetch(`/api/history/?user_id=${encodeURIComponent(userId)}`, {
        headers: {
          'X-User-Id': userId
        }
      });
      const data = await res.json();
      
      if (data.history && historyTableBody) {
        if (data.history.length === 0) {
          historyTableBody.innerHTML = `
            <tr>
              <td colspan="4" class="empty-history-cell">
                Hech qanday yuklanma topilmadi. Boshlash uchun yuqoridagi manzilni tekshiring!
              </td>
            </tr>
          `;
          return;
        }

        historyTableBody.innerHTML = data.history.map(item => `
          <tr>
            <td data-label="Sarlavha & Sana">
              <strong class="item-title">${escapeHtml(item.title)}</strong>
              <div class="item-date">${item.created_at}</div>
            </td>
            <td data-label="Turi"><span class="badge-type ${item.media_type}">${item.media_type}</span></td>
            <td data-label="Format">${escapeHtml(item.format_label || 'Auto')}</td>
            <td data-label="Harakat">
              <div class="history-row-actions">
                ${(item.download_url || (item.original_url && (item.original_url.startsWith('http://') || item.original_url.startsWith('https://')))) ? `<a href="${escapeHtml(item.download_url || item.original_url)}" target="_blank" rel="noopener noreferrer" class="btn-file-dl">📥 Yuklab olish</a>` : ''}
                <button class="btn-delete-row" data-id="${item.id}" type="button" title="O'chirish">
                  🗑️
                </button>
              </div>
            </td>
          </tr>
        `).join('');
      }
    } catch (e) {}
  }

  // Utilities
  function setLoading(btn, isLoading, text) {
    if (isLoading) {
      btn.disabled = true;
      btn.innerHTML = `<div class="spinner"></div> ${text}`;
    } else {
      btn.disabled = false;
      btn.innerHTML = text;
    }
  }

  function roundMB(bytes) {
    return (bytes / (1024 * 1024)).toFixed(2);
  }

  function escapeHtml(str) {
    return str.replace(/[&<>'"]/g, 
      tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
    );
  }

  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.style.cssText = `
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: ${type === 'error' ? 'rgba(244, 63, 94, 0.9)' : 'rgba(16, 185, 129, 0.9)'};
      color: #fff;
      padding: 12px 20px;
      border-radius: 10px;
      font-weight: 600;
      box-shadow: 0 10px 25px rgba(0,0,0,0.3);
      z-index: 9999;
      animation: fadeIn 0.3s ease;
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }

  // --- Google Auth Client Controller ---
  const gAuthUnauth = document.getElementById('gAuthUnauth');
  const gAuthAuth = document.getElementById('gAuthAuth');
  const btnGoogleSignIn = document.getElementById('btnGoogleSignIn');
  const btnLogout = document.getElementById('btnLogout');
  const userAvatar = document.getElementById('userAvatar');
  const userName = document.getElementById('userName');
  const userEmail = document.getElementById('userEmail');

  const btnGoogleAuthLogin = document.getElementById('btnGoogleAuthLogin');
  const btnGoogleAuthRegister = document.getElementById('btnGoogleAuthRegister');

  const DEFAULT_AVATAR_SVG = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="%2300f2fe"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z"/></svg>';

  function renderAuthUser(user) {
    if (!user) return renderUnauth();
    if (gAuthUnauth) gAuthUnauth.style.display = 'none';
    if (gAuthAuth) gAuthAuth.style.display = 'block';

    if (userName) userName.textContent = user.name || user.first_name || user.email || 'Foydalanuvchi';
    if (userEmail) userEmail.textContent = user.email || '';
    if (userAvatar) userAvatar.src = user.picture || DEFAULT_AVATAR_SVG;
  }

  function renderUnauth() {
    if (gAuthUnauth) gAuthUnauth.style.display = 'block';
    if (gAuthAuth) gAuthAuth.style.display = 'none';
  }

  async function checkAuthStatus() {
    try {
      const res = await fetch('/api/auth/me/');
      const data = await res.json();
      if (data.is_authenticated && data.user) {
        renderAuthUser(data.user);
      } else {
        renderUnauth();
      }
    } catch (e) {
      renderUnauth();
    }
  }

  async function sendGoogleTokenToBackend(payload) {
    try {
      const res = await fetch('/api/auth/google/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.status === 'success' && data.user) {
        renderAuthUser(data.user);
        showToast(`Xush kelibsiz, ${data.user.name}!`, 'success');
        refreshHistory();

        setTimeout(() => {
          window.location.href = data.redirect_url || '/';
        }, 300);
      } else {
        showToast(data.error || 'Google kirishda xatolik yuz berdi.', 'error');
      }
    } catch (err) {
      showToast('Authentication error.', 'error');
    }
  }


  window.handleGoogleCredentialResponse = async function(googleResponse) {
    if (!googleResponse) return;
    const token = googleResponse.credential || googleResponse.id_token;
    if (token) {
      await sendGoogleTokenToBackend({ credential: token, id_token: token });
    }
  };

  function checkGoogleOAuthHashCallback() {
    if (window.location.hash && (window.location.hash.includes('access_token=') || window.location.hash.includes('id_token='))) {
      const hashParams = new URLSearchParams(window.location.hash.substring(1));
      const accessToken = hashParams.get('access_token');
      const idToken = hashParams.get('id_token');

      if (accessToken || idToken) {
        try {
          history.replaceState(null, '', window.location.pathname);
        } catch (e) {}
        sendGoogleTokenToBackend({ access_token: accessToken, id_token: idToken });
      }
    }
  }

  function getGoogleClientId() {
    const metaClientId = document.querySelector('meta[name="google-client-id"]');
    const clientId = metaClientId ? metaClientId.content : '';
    if (!clientId || clientId === 'YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com') {
      return '';
    }
    return clientId;
  }

  function setupGIS() {
    const clientId = getGoogleClientId();
    if (window.google && google.accounts && google.accounts.id && clientId) {
      google.accounts.id.initialize({
        client_id: clientId,
        callback: window.handleGoogleCredentialResponse,
        auto_prompt: false
      });
    }
  }

  function triggerGoogleFlow(e) {
    if (e && typeof e.preventDefault === 'function') {
      e.preventDefault();
    }
    const clientId = getGoogleClientId();

    if (!clientId) {
      showToast('Google OAuth Client ID sozlanmagan. Proyekt sozlamalarida GOOGLE_CLIENT_ID manzilini kiriting.', 'info');
      return;
    }

    const redirectUri = window.location.origin + '/login/';
    const scope = encodeURIComponent('email profile openid');
    const authUrl = `https://accounts.google.com/o/oauth2/v2/auth?client_id=${clientId}&redirect_uri=${encodeURIComponent(redirectUri)}&response_type=token&scope=${scope}&prompt=select_account`;

    // Direct single-tab redirect: 100% reliable, zero popups, zero double-window conflicts
    window.location.href = authUrl;
  }





  if (btnGoogleSignIn) {
    btnGoogleSignIn.addEventListener('click', triggerGoogleFlow);
  }
  if (btnGoogleAuthLogin) {
    btnGoogleAuthLogin.addEventListener('click', triggerGoogleFlow);
  }
  if (btnGoogleAuthRegister) {
    btnGoogleAuthRegister.addEventListener('click', triggerGoogleFlow);
  }

  checkGoogleOAuthHashCallback();

  if (btnLogout) {
    btnLogout.addEventListener('click', async () => {
      try {
        const res = await fetch('/api/auth/logout/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
          }
        });
        const data = await res.json();
        renderUnauth();
        showToast('Tizimdan muvaffaqiyatli chiqdingiz.', 'info');
        refreshHistory();
      } catch (err) {
        showToast('Logout xatosi.', 'error');
      }
    });
  }

  // Initial Auth Check & GIS Init
  checkAuthStatus();
  setTimeout(setupGIS, 800);
});

/* ==========================================================================
   Global Auth Page Interactivity (Tab Switch, Password Meter, Submit)
   ========================================================================== */

function switchAuthTab(tabName) {
  const tabLogin = document.getElementById('tabLogin');
  const tabSignup = document.getElementById('tabSignup');
  const formLogin = document.getElementById('formLogin');
  const formRegister = document.getElementById('formRegister');
  const authAlert = document.getElementById('authAlert');

  if (authAlert) authAlert.style.display = 'none';

  if (tabName === 'login') {
    if (tabLogin) tabLogin.classList.add('active');
    if (tabSignup) tabSignup.classList.remove('active');
    if (formLogin) formLogin.classList.remove('hidden-form');
    if (formRegister) formRegister.classList.add('hidden-form');
  } else {
    if (tabSignup) tabSignup.classList.add('active');
    if (tabLogin) tabLogin.classList.remove('active');
    if (formRegister) formRegister.classList.remove('hidden-form');
    if (formLogin) formLogin.classList.add('hidden-form');
  }
}

function togglePasswordVisibility(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;

  if (input.type === 'password') {
    input.type = 'text';
    btn.innerHTML = `
      <svg class="icon-eye-off" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
        <line x1="1" y1="1" x2="23" y2="23"></line>
      </svg>
    `;
    btn.title = "Parolni berkitish";
  } else {
    input.type = 'password';
    btn.innerHTML = `
      <svg class="icon-eye" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
        <circle cx="12" cy="12" r="3"></circle>
      </svg>
    `;
    btn.title = "Parolni ko'rsatish";
  }
}

function evaluatePasswordStrength(password) {
  const fill = document.getElementById('pwdStrengthFill');
  const label = document.getElementById('pwdStrengthLabel');
  const critLength = document.getElementById('critLength');
  const critMix = document.getElementById('critMix');

  if (!fill || !label) return;

  const lenOk = password.length >= 6;
  const mixOk = /[A-Za-z]/.test(password) && (/\d/.test(password) || /[^A-Za-z0-9]/.test(password));

  if (critLength) {
    critLength.classList.toggle('valid', lenOk);
    critLength.querySelector('.crit-icon').textContent = lenOk ? '✓' : '✕';
  }

  if (critMix) {
    critMix.classList.toggle('valid', mixOk);
    critMix.querySelector('.crit-icon').textContent = mixOk ? '✓' : '✕';
  }

  if (!password) {
    fill.className = 'pwd-meter-fill strength-none';
    label.textContent = 'Kiritilmagan';
    return;
  }

  let score = 0;
  if (password.length >= 6) score++;
  if (password.length >= 10) score++;
  if (/[A-Z]/.test(password) && /[a-z]/.test(password)) score++;
  if (/\d/.test(password)) score++;
  if (/[^A-Za-z0-9]/.test(password)) score++;

  if (score <= 1) {
    fill.className = 'pwd-meter-fill strength-weak';
    label.textContent = 'Zaif';
  } else if (score === 2 || score === 3) {
    fill.className = 'pwd-meter-fill strength-fair';
    label.textContent = 'O\'rtacha';
  } else if (score === 4) {
    fill.className = 'pwd-meter-fill strength-good';
    label.textContent = 'Yaxshi';
  } else {
    fill.className = 'pwd-meter-fill strength-strong';
    label.textContent = 'Mustahkam / A\'lo';
  }
}

function checkPasswordMatch() {
  const pwd = document.getElementById('regPassword')?.value || '';
  const confirmPwd = document.getElementById('regConfirmPassword')?.value || '';
  const statusDiv = document.getElementById('pwdMatchStatus');

  if (!statusDiv) return;

  if (!confirmPwd) {
    statusDiv.style.display = 'none';
    return;
  }

  statusDiv.style.display = 'block';
  if (pwd === confirmPwd) {
    statusDiv.className = 'pwd-match-hint match-success';
    statusDiv.textContent = '✓ Parollar mos keldi';
  } else {
    statusDiv.className = 'pwd-match-hint match-error';
    statusDiv.textContent = '✕ Parollar bir xil emas!';
  }
}

function displayAuthAlert(message, type = 'error') {
  const alert = document.getElementById('authAlert');
  if (!alert) return;

  alert.className = `auth-alert alert-${type}`;
  alert.innerHTML = `
    <span>${type === 'error' ? '⚠️' : '✅'}</span>
    <span>${message}</span>
  `;
  alert.style.display = 'flex';
}

function setAuthButtonState(buttonId, isLoading, defaultText) {
  const btn = document.getElementById(buttonId);
  if (!btn) return;

  const btnText = btn.querySelector('.btn-text');
  const spinner = btn.querySelector('.btn-spinner');
  const icon = btn.querySelector('.btn-icon');

  if (isLoading) {
    btn.disabled = true;
    if (btnText) btnText.textContent = 'Bajarilmoqda...';
    if (spinner) spinner.style.display = 'block';
    if (icon) icon.style.display = 'none';
  } else {
    btn.disabled = false;
    if (btnText) btnText.textContent = defaultText;
    if (spinner) spinner.style.display = 'none';
    if (icon) icon.style.display = 'block';
  }
}

function getCsrfToken() {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, 10) === ('csrftoken=')) {
        cookieValue = decodeURIComponent(cookie.substring(10));
        break;
      }
    }
  }
  if (!cookieValue) {
    const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (csrfInput) cookieValue = csrfInput.value;
  }
  return cookieValue;
}

async function handleLoginSubmit(e) {
  e.preventDefault();
  const loginId = document.getElementById('loginId')?.value.trim();
  const password = document.getElementById('loginPassword')?.value.trim();

  if (!loginId || !password) {
    displayAuthAlert('Barcha maydonlarni to\'ldiring.');
    return;
  }

  setAuthButtonState('btnLoginSubmit', true, 'Kirish');

  try {
    const res = await fetch('/api/auth/login/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      },
      body: JSON.stringify({ login_id: loginId, password: password })
    });

    const data = await res.json();
    setAuthButtonState('btnLoginSubmit', false, 'Kirish');

    if (res.ok && data.status === 'success') {
      displayAuthAlert(data.message || 'Muvaffaqiyatli kirdingiz!', 'success');
      const targetUrl = data.redirect_url || '/';
      setTimeout(() => {
        window.location.href = targetUrl;
      }, 700);
    } else {
      displayAuthAlert(data.error || 'Kirishda xatolik yuz berdi.');
    }
  } catch (err) {
    setAuthButtonState('btnLoginSubmit', false, 'Kirish');
    displayAuthAlert('Server bilan bog\'lanishda xatolik yuz berdi.');
  }
}

let pendingRegEmail = '';
let verifyTimerInterval = null;
let resendCooldownInterval = null;

async function handleRegisterSubmit(e) {
  e.preventDefault();
  const firstName = document.getElementById('regFirstName')?.value.trim();
  const lastName = document.getElementById('regLastName')?.value.trim();
  const username = document.getElementById('regUsername')?.value.trim();
  const email = document.getElementById('regEmail')?.value.trim().toLowerCase();
  const password = document.getElementById('regPassword')?.value.trim();
  const confirmPassword = document.getElementById('regConfirmPassword')?.value.trim();

  if (!username || !email || !password) {
    displayAuthAlert('Talab qilingan barcha maydonlarni to\'ldiring.');
    return;
  }

  if (password !== confirmPassword) {
    displayAuthAlert('Parollar mos kelmadi. Iltimos tekshiring.');
    return;
  }

  setAuthButtonState('btnRegisterSubmit', true, 'Tasdiqlash kodi yuborilmoqda...');
  pendingRegEmail = email;

  try {
    const res = await fetch('/api/auth/register/send-code/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      },
      body: JSON.stringify({
        username: username,
        email: email,
        password: password,
        first_name: firstName,
        last_name: lastName
      })
    });

    const data = await res.json();
    setAuthButtonState('btnRegisterSubmit', false, 'Ro\'yxatdan o\'tish');

    if (res.ok && data.status === 'success') {
      displayAuthAlert(data.message || 'Tasdiqlash kodi emailingizga yuborildi!', 'success');

      const formReg = document.getElementById('formRegister');
      const formVerify = document.getElementById('formVerifyCode');
      const emailTarget = document.getElementById('verifyEmailTarget');

      if (formReg) formReg.classList.add('hidden-form');
      if (formVerify) formVerify.classList.remove('hidden-form');
      if (emailTarget) emailTarget.textContent = email;

      startVerifyTimer(data.expires_in_seconds || 600);
      startResendCooldown(data.cooldown_seconds || 120);

    } else {
      displayAuthAlert(data.error || 'Tasdiqlash kodini yuborishda xatolik yuz berdi.');
    }
  } catch (err) {
    setAuthButtonState('btnRegisterSubmit', false, 'Ro\'yxatdan o\'tish');
    displayAuthAlert('Server bilan bog\'lanishda xatolik yuz berdi.');
  }
}

async function handleVerifyCodeSubmit(e) {
  e.preventDefault();
  const code = document.getElementById('verifyCodeInput')?.value.trim();
  if (!code || code.length !== 6) {
    displayAuthAlert('6 xonali tasdiqlash kodini kiriting.');
    return;
  }

  setAuthButtonState('btnVerifyCodeSubmit', true, 'Kodni Tekshirish...');

  try {
    const res = await fetch('/api/auth/register/verify/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      },
      body: JSON.stringify({
        email: pendingRegEmail,
        code: code
      })
    });

    const data = await res.json();
    setAuthButtonState('btnVerifyCodeSubmit', false, 'Kodni Tasdiqlash va Kirish');

    if (res.ok && data.status === 'success') {
      displayAuthAlert(data.message || 'Muvaffaqiyatli ro\'yxatdan o\'tdingiz!', 'success');
      const targetUrl = data.redirect_url || '/';
      setTimeout(() => {
        window.location.href = targetUrl;
      }, 700);
    } else {
      displayAuthAlert(data.error || 'Tasdiqlash kodi noto\'g\'ri.');
    }
  } catch (err) {
    setAuthButtonState('btnVerifyCodeSubmit', false, 'Kodni Tasdiqlash va Kirish');
    displayAuthAlert('Server bilan bog\'lanishda xatolik.');
  }
}

async function handleResendCode() {
  if (!pendingRegEmail) return;
  const btn = document.getElementById('btnResendCode');
  if (btn) btn.disabled = true;

  displayAuthAlert('Yangi tasdiqlash kodi yuborilmoqda...', 'success');

  try {
    const res = await fetch('/api/auth/register/send-code/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      },
      body: JSON.stringify({
        email: pendingRegEmail,
        username: document.getElementById('regUsername')?.value.trim(),
        password: document.getElementById('regPassword')?.value.trim(),
      })
    });

    const data = await res.json();
    if (res.ok && data.status === 'success') {
      displayAuthAlert('Yangi kod yuborildi (10 daqiqa amal qiladi)!', 'success');
      startVerifyTimer(data.expires_in_seconds || 600);
      startResendCooldown(data.cooldown_seconds || 120);
    } else {
      displayAuthAlert(data.error || 'Qayta yuborishda xatolik.');
    }
  } catch (e) {
    displayAuthAlert('Server xatosi.');
  }
}

function startVerifyTimer(seconds) {
  if (verifyTimerInterval) clearInterval(verifyTimerInterval);
  let remaining = seconds;
  const countEl = document.getElementById('verifyTimerCount');

  const update = () => {
    if (remaining <= 0) {
      clearInterval(verifyTimerInterval);
      if (countEl) countEl.textContent = 'Muddati tugadi (00:00)';
      displayAuthAlert('Kod vaqti (10 daqiqa) tugadi. Yangi kod so\'rang.', 'error');
      return;
    }
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    if (countEl) countEl.textContent = `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    remaining--;
  };

  update();
  verifyTimerInterval = setInterval(update, 1000);
}

function startResendCooldown(seconds) {
  if (resendCooldownInterval) clearInterval(resendCooldownInterval);
  let remaining = seconds;
  const btn = document.getElementById('btnResendCode');
  const countEl = document.getElementById('resendCooldownCount');

  if (btn) {
    btn.disabled = true;
    btn.style.opacity = '0.6';
    btn.style.cursor = 'not-allowed';
  }

  const update = () => {
    if (remaining <= 0) {
      clearInterval(resendCooldownInterval);
      if (btn) {
        btn.disabled = false;
        btn.style.opacity = '1';
        btn.style.cursor = 'pointer';
        btn.innerHTML = '🔄 Yangi Kod Yuborish';
      }
      return;
    }
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    if (countEl) countEl.textContent = `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    remaining--;
  };

  update();
  resendCooldownInterval = setInterval(update, 1000);
}

window.handleRegisterSubmit = handleRegisterSubmit;
window.handleVerifyCodeSubmit = handleVerifyCodeSubmit;
window.handleResendCode = handleResendCode;


