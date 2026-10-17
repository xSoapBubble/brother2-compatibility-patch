# Исправления версии 1.0

Это описание поведения и связи с исходниками. Список поддерживаемых байтов
и хешей находится в `patches/engine-manifest.json`; порядок генераторов —
в `tools/engine.py`. Каждый этап проверяет свой исходный вариант.

| Область | Реализация |
| --- | --- |
| Старый DirectDraw/Direct3D, форматы текстур, прозрачность теней | Неизменённый DDrawCompat и `resources/DDrawCompat.ini` |
| Ошибки старого пула памяти | `patch_zbase_allocator.py` |
| Замедление при длительной работе Windows | `patch_clock_origin.py`: целочисленное вычитание начала отсчёта до преобразования времени |
| Очередь мыши, курсор, возврат фокуса | `patch_zplayer_mouse_queue.py`, `zsol_mouse_payload.py` |
| Ограничение избыточной отрисовки | `patch_zplayer_frame_pacing.py` |
| Загрузка/повторная загрузка, движение окна и синхронизация ввода | `patch_zplayer_ui_lifecycle_gate.py`, `patch_zplayer_deferred_window_move.py` |
| Старт окна без наведения мыши, Alt, сохранение Alt+Tab/Alt+F4 | `patch_startup_message_loop.py`, `patch_alt_system_menu.py` |
| Разрушение стекла, эффекты, владение объектами | `patch_zsol_compatibility.py`, `patch_zsol_*ownership.py`, `patch_zsol_explosion_serialization.py` |
| Поворот камеры и взаимодействие с интерфейсом | `patch_zsol_pitch_limit.py`, `patch_zgui_gameplay_hit_test.py` |
| Строки меню и сохранений | `patch_zsol_select_string.py`, `patch_zgui_click_string.py`, `patch_zgui_string_assignments.py` |
| Пустые слоты, полноэкранные снимки сохранений | `patch_empty_slot_previews.py`, `patch_zgui_preview_decoder.py` |
| Обрезанный текст, положение описания, дальномер | `patch_text_clip_bounds_v2.py`, `patch_save_tooltip_position.py`, `patch_rangefinder_bounds.py` |
| Удержание оптики, движение и прыжки | `patch_zsol_zoom_hold.py`, `patch_zplayer_prestep_keys.py`, `patch_zplayer_prestep_focus.py`, `patch_zsol_jump_ground_band.py` |
| Регуляторы громкости и сохранение значений | `patch_audio_bridges.py`, `src/runtime/rea_audio_*.c` |
| Возвращение звука при смене/переподключении устройства | `patch_audio_device_proxy.py`, `src/runtime/rea_audio_device_proxy.cpp` |
| Отчёт только при проблеме или ручном запросе | `src/diagnostics/` |
| Русское имя ярлыка на Windows с другим системным языком | `src/installer/BrotherPatch.cs`: Unicode IShellLinkW/IPersistFile |

## Возвращение аудиоустройства

Первый вариант простого Restore убирал исключение, но звук не возвращался.
Пересоздание всего устройства восстановило буферы, однако при временном
исчезновении HDMI-выхода игра могла остаться на запасном устройстве.

Текущий компонент сохраняет COM-интерфейсы, копии PCM и состояние 3D-буферов,
транзакционно пересоздаёт backend, отслеживает default mapping DirectSound и
значимые уведомления аудиоустройств. Старые уведомления проигрывания
отбрасываются. Основной поток игры не выполняет запросы Core Audio.

Возвращение слышимого звука после переподключения AVT GC570 подтверждено
проверкой на оборудовании. Синтетические тесты отдельно проверяют буферы,
громкость, события, переходы A→B→A и время жизни обработчиков.

Отдельная музыка оригинала использует Audio CD. Образ с одними файлами данных
не содержит музыкальных дорожек; патч не добавляет отсутствующую музыку.
