# window.py
#
# Copyright 2026 MM 喵了个
#
# SPDX-License-Identifier: LGPL-3.0-or-later

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from gi.repository import Adw, Gtk, GLib
from .engine import PackManager, AudioPlayer, AudioSegment


@Gtk.Template(resource_path='/com/github/mimiaomc/nextstop/window.ui')
class NextstopWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'NextstopWindow'

    # 顶栏与主容器
    pack_dropdown = Gtk.Template.Child()
    refresh_pack_btn = Gtk.Template.Child()
    switcher_title = Gtk.Template.Child()
    view_stack = Gtk.Template.Child()
    toast_overlay = Gtk.Template.Child()

    # 出站 / 下一站
    depart_group = Gtk.Template.Child()
    depart_station_entry = Gtk.Template.Child()
    depart_station_dropdown = Gtk.Template.Child()
    depart_intro_entry = Gtk.Template.Child()
    depart_intro_clear_btn = Gtk.Template.Child()
    depart_intro_dropdown = Gtk.Template.Child()
    depart_transfer_expander = Gtk.Template.Child()

    # 进站 / 到站
    arrive_group = Gtk.Template.Child()
    arrive_station_entry = Gtk.Template.Child()
    arrive_sync_btn = Gtk.Template.Child()
    arrive_station_dropdown = Gtk.Template.Child()
    arrive_chime_row = Gtk.Template.Child()
    arrive_ad_row = Gtk.Template.Child()

    # 车外进站广播（外报）
    outside_group = Gtk.Template.Child()
    outside_line_entry = Gtk.Template.Child()
    outside_line_dropdown = Gtk.Template.Child()
    outside_dest_entry = Gtk.Template.Child()
    outside_dest_dropdown = Gtk.Template.Child()
    outside_play_btn = Gtk.Template.Child()

    # 动态容器组
    global_switches_group = Gtk.Template.Child()
    quick_clips_group = Gtk.Template.Child()

    # 首末站
    first_line_row = Gtk.Template.Child()
    first_origin_row = Gtk.Template.Child()
    first_dest_row = Gtk.Template.Child()
    first_play_btn = Gtk.Template.Child()

    terminus_station_row = Gtk.Template.Child()
    terminus_play_btn = Gtk.Template.Child()

    # 底栏播放器
    bottom_mute_btn = Gtk.Template.Child()
    bottom_title_label = Gtk.Template.Child()
    bottom_route_label = Gtk.Template.Child()
    bottom_subtitle_label = Gtk.Template.Child()
    bottom_counter_label = Gtk.Template.Child()
    bottom_progress = Gtk.Template.Child()
    bottom_pause_btn = Gtk.Template.Child()
    bottom_skip_btn = Gtk.Template.Child()
    bottom_stop_btn = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.pack_manager = PackManager()
        self.player = AudioPlayer()

        # 保存动态创建的控件引用以便切换语音包时清理
        self._dynamic_depart_rows: List[Gtk.Widget] = []
        self._dynamic_arrive_rows: List[Gtk.Widget] = []
        self._dynamic_global_rows: List[Gtk.Widget] = []
        self._dynamic_quick_rows: List[Gtk.Widget] = []
        self._dynamic_transfer_rows: List[Gtk.Widget] = []

        self._switch_widgets: Dict[str, Adw.SwitchRow] = {}
        self._transfer_switch_widgets: Dict[str, Adw.SwitchRow] = {}

        self._updating_packs = False
        self._syncing_route = False

        self._setup_signals()
        self._populate_pack_dropdown()
        self._rebuild_pack_ui()

    def _get_row_selected_text(self, row: Adw.ComboRow) -> str:
        idx = row.get_selected()
        model = row.get_model()
        if model and idx < model.get_n_items():
            return model.get_string(idx)
        return ""

    def _populate_pack_dropdown(self):
        self._updating_packs = True
        pack_names = [p.name for p in self.pack_manager.available_packs] or ["西安公交（标准版）"]
        self.pack_dropdown.set_model(Gtk.StringList.new(pack_names))
        if self.pack_manager.current_pack:
            for i, p in enumerate(self.pack_manager.available_packs):
                if p.id == self.pack_manager.current_pack.id:
                    self.pack_dropdown.set_selected(i)
                    break
        self._updating_packs = False

    def _clear_dynamic_rows(self):
        for w in self._dynamic_depart_rows:
            self.depart_group.remove(w)
        self._dynamic_depart_rows.clear()

        for w in self._dynamic_arrive_rows:
            self.arrive_group.remove(w)
        self._dynamic_arrive_rows.clear()

        for w in self._dynamic_global_rows:
            self.global_switches_group.remove(w)
        self._dynamic_global_rows.clear()

        for w in self._dynamic_quick_rows:
            self.quick_clips_group.remove(w)
        self._dynamic_quick_rows.clear()

        for w in self._dynamic_transfer_rows:
            self.depart_transfer_expander.remove(w)
        self._dynamic_transfer_rows.clear()
        self._transfer_switch_widgets.clear()

        self._switch_widgets.clear()

    def _rebuild_pack_ui(self):
        """根据当前 pack.json 动态构建所有下拉菜单、特性开关、站点触发行与快捷口令"""
        self._clear_dynamic_rows()

        stations = self.pack_manager.stations or ["小寨站"]
        picker_items = ["选素材库已有站点..."] + stations
        self.depart_station_dropdown.set_model(Gtk.StringList.new(picker_items))
        self.arrive_station_dropdown.set_model(Gtk.StringList.new(picker_items))
        self.outside_dest_dropdown.set_model(Gtk.StringList.new(picker_items))
        self.depart_station_dropdown.set_selected(0)
        self.arrive_station_dropdown.set_selected(0)
        self.outside_dest_dropdown.set_selected(0)

        intros = self.pack_manager.intros or []
        intro_picker_items = ["选已有介绍...", "不插播介绍"] + intros
        self.depart_intro_dropdown.set_model(Gtk.StringList.new(intro_picker_items))
        self.depart_intro_dropdown.set_selected(0)
        self.depart_intro_entry.set_text("")

        self.first_origin_row.set_model(Gtk.StringList.new(stations))
        self.first_dest_row.set_model(Gtk.StringList.new(stations))
        self.terminus_station_row.set_model(Gtk.StringList.new(stations))

        # 构建换乘线路多选开关
        transfer_list = [t for t in self.pack_manager.transfers if t and t != "无换乘"]
        for line_name in transfer_list:
            row = Adw.SwitchRow(title=line_name, active=False)
            row.connect("notify::active", self._on_transfer_switch_toggled)
            self.depart_transfer_expander.add_row(row)
            self._dynamic_transfer_rows.append(row)
            self._transfer_switch_widgets[line_name] = row
        self._update_transfer_expander_subtitle()

        self.arrive_chime_row.set_model(Gtk.StringList.new(self.pack_manager.chimes))
        self.arrive_chime_row.set_selected(0)

        self.arrive_ad_row.set_model(Gtk.StringList.new(self.pack_manager.ads))

        lines = self.pack_manager.lines or ["333 路无人售票车"]
        line_picker_items = ["选已有线路..."] + lines
        self.outside_line_dropdown.set_model(Gtk.StringList.new(line_picker_items))
        self.outside_line_dropdown.set_selected(0)
        self.first_line_row.set_model(Gtk.StringList.new(lines))

        # 读取 pack.json 默认值
        defaults = self.pack_manager.config.get("defaults", {})
        def_station = defaults.get("station", "小寨")
        def_origin = defaults.get("origin", "西北工业大学")
        def_dest = defaults.get("destination", "城南公交枢纽")
        def_line = defaults.get("line", "333")

        self._syncing_route = True
        for i, s in enumerate(stations):
            if def_station in s:
                self.depart_station_entry.set_text(s)
                self.arrive_station_entry.set_text(s)
            if def_origin in s:
                self.first_origin_row.set_selected(i)
            if def_dest in s:
                self.outside_dest_entry.set_text(s)
                self.first_dest_row.set_selected(i)
                self.terminus_station_row.set_selected(i)

        for i, ln in enumerate(lines):
            if def_line in ln:
                self.outside_line_entry.set_text(ln)
                self.first_line_row.set_selected(i)
                break
        self._syncing_route = False
        self._update_bottom_route_label()

        # 1. 动态生成出站卡片开关（如：965 315 热线、爱上大西安、下一站是终点站）
        for sw_cfg in self.pack_manager.get_switches(placement="depart"):
            row = Adw.SwitchRow(
                title=sw_cfg.get("title", ""),
                subtitle=sw_cfg.get("subtitle", ""),
                active=bool(sw_cfg.get("default", False)),
            )
            self.depart_group.add(row)
            self._dynamic_depart_rows.append(row)
            self._switch_widgets[sw_cfg["id"]] = row

        # 2. 出站与到站的播放主按钮行（始终置于各卡片底部）
        dep_action = Adw.ActionRow(
            title="播放出站广播",
            subtitle="按当前语音包规则拼装并播报出站语音队列",
        )
        dep_btn = Gtk.Button(
            label="播报起步",
            icon_name="media-playback-start-symbolic",
            valign=Gtk.Align.CENTER,
            css_classes=["suggested-action"],
        )
        dep_btn.connect("clicked", self._on_depart_play)
        dep_action.add_suffix(dep_btn)
        self.depart_group.add(dep_action)
        self._dynamic_depart_rows.append(dep_action)

        # 动态生成到站卡片开关（如：本站是终点站）
        for sw_cfg in self.pack_manager.get_switches(placement="arrive"):
            row = Adw.SwitchRow(
                title=sw_cfg.get("title", ""),
                subtitle=sw_cfg.get("subtitle", ""),
                active=bool(sw_cfg.get("default", False)),
            )
            self.arrive_group.add(row)
            self._dynamic_arrive_rows.append(row)
            self._switch_widgets[sw_cfg["id"]] = row

        arr_action = Adw.ActionRow(
            title="播放到站广播",
            subtitle="提示音 - 商业广告 - 到站 - 下车安全提醒",
        )
        arr_btn = Gtk.Button(
            label="播报到站",
            icon_name="media-playback-start-symbolic",
            valign=Gtk.Align.CENTER,
            css_classes=["suggested-action"],
        )
        arr_btn.connect("clicked", self._on_arrive_play)
        arr_action.add_suffix(arr_btn)
        self.arrive_group.add(arr_action)
        self._dynamic_arrive_rows.append(arr_action)

        # 4. 动态生成全局车型与特性开关（如双层巴士、响应式停靠、225路换乘尾音）
        for sw_cfg in self.pack_manager.get_switches(placement="global"):
            row = Adw.SwitchRow(
                title=sw_cfg.get("title", ""),
                subtitle=sw_cfg.get("subtitle", ""),
                active=bool(sw_cfg.get("default", False)),
            )
            self.global_switches_group.add(row)
            self._dynamic_global_rows.append(row)
            self._switch_widgets[sw_cfg["id"]] = row

        # 5. 动态生成单项快捷口令列表
        for clip in self.pack_manager.get_quick_clips():
            title = clip.get("title", "")
            label = clip.get("label", title)
            rel_file = clip.get("file", "")
            row = Adw.ActionRow(title=title)
            btn = Gtk.Button(
                icon_name="media-playback-start-symbolic",
                valign=Gtk.Align.CENTER,
                css_classes=["flat"],
            )
            btn.connect(
                "clicked",
                lambda _b, l=label, rf=rel_file: self._play_rel_single(l, rf),
            )
            row.add_suffix(btn)
            self.quick_clips_group.add(row)
            self._dynamic_quick_rows.append(row)

    def _setup_signals(self):
        """绑定按钮动作与播放器事件"""
        self.player.on_segment_start = self._on_segment_start
        self.player.on_pause_changed = self._on_pause_changed
        self.player.on_finished = self._on_playback_finished
        self.player.on_error = self._on_playback_error

        # 顶栏语音包切换与热刷新
        self.pack_dropdown.connect("notify::selected", self._on_pack_selected)
        self.refresh_pack_btn.connect("clicked", self._on_refresh_pack_clicked)

        # 站点输入框右侧快捷选站与同步按钮
        self.depart_station_dropdown.connect("notify::selected", self._on_depart_dropdown_selected)
        self.depart_intro_dropdown.connect("notify::selected", self._on_depart_intro_dropdown_selected)
        self.depart_intro_clear_btn.connect("clicked", lambda *_: self.depart_intro_entry.set_text(""))
        self.arrive_station_dropdown.connect("notify::selected", self._on_arrive_dropdown_selected)
        self.arrive_sync_btn.connect("clicked", self._on_arrive_sync_clicked)

        # 外报线路与终点站快捷下拉菜单与联动
        self.outside_line_dropdown.connect("notify::selected", self._on_outside_line_dropdown_selected)
        self.outside_dest_dropdown.connect("notify::selected", self._on_outside_dest_dropdown_selected)
        self.outside_line_entry.connect("changed", self._on_outside_route_entry_changed)
        self.outside_dest_entry.connect("changed", self._on_outside_route_entry_changed)
        self.first_line_row.connect("notify::selected", self._on_first_route_combo_changed)
        self.first_dest_row.connect("notify::selected", self._on_first_route_combo_changed)

        # 首末站与车外按钮
        self.first_play_btn.connect("clicked", self._on_first_play)
        self.terminus_play_btn.connect("clicked", self._on_terminus_play)
        self.outside_play_btn.connect("clicked", self._on_outside_play)

        # 底栏控制（静音、暂停、跳过当前片段、停止）
        self.bottom_mute_btn.connect("clicked", self._on_mute_clicked)
        self.bottom_pause_btn.connect("clicked", lambda *_: self.player.toggle_pause())
        self.bottom_skip_btn.connect("clicked", lambda *_: self.player.skip_next())
        self.bottom_stop_btn.connect("clicked", lambda *_: self.player.stop())

    def _on_pack_selected(self, *args):
        if self._updating_packs:
            return
        idx = self.pack_dropdown.get_selected()
        if idx < len(self.pack_manager.available_packs):
            pack = self.pack_manager.available_packs[idx]
            self.pack_manager.load_pack(pack.id)
            self._rebuild_pack_ui()
            self._show_toast(f"已切换语音包：{pack.name}")

    def _on_refresh_pack_clicked(self, *args):
        self.pack_manager.reload_current_pack()
        self._populate_pack_dropdown()
        self._rebuild_pack_ui()
        self._show_toast(f"已刷新素材库（共 {len(self.pack_manager.stations)} 个站点）")

    def _on_depart_dropdown_selected(self, *args):
        idx = self.depart_station_dropdown.get_selected()
        if idx > 0:
            model = self.depart_station_dropdown.get_model()
            st = model.get_string(idx)
            self.depart_station_entry.set_text(st)
            GLib.idle_add(lambda: self.depart_station_dropdown.set_selected(0))

    def _on_depart_intro_dropdown_selected(self, *args):
        idx = self.depart_intro_dropdown.get_selected()
        if idx == 1:
            self.depart_intro_entry.set_text("")
            GLib.idle_add(lambda: self.depart_intro_dropdown.set_selected(0))
        elif idx > 1:
            model = self.depart_intro_dropdown.get_model()
            intro_name = model.get_string(idx)
            self.depart_intro_entry.set_text(intro_name)
            GLib.idle_add(lambda: self.depart_intro_dropdown.set_selected(0))

    def _on_arrive_dropdown_selected(self, *args):
        idx = self.arrive_station_dropdown.get_selected()
        if idx > 0:
            model = self.arrive_station_dropdown.get_model()
            st = model.get_string(idx)
            self.arrive_station_entry.set_text(st)
            GLib.idle_add(lambda: self.arrive_station_dropdown.set_selected(0))

    def _on_outside_line_dropdown_selected(self, *args):
        idx = self.outside_line_dropdown.get_selected()
        if idx > 0:
            model = self.outside_line_dropdown.get_model()
            ln = model.get_string(idx)
            self.outside_line_entry.set_text(ln)
            GLib.idle_add(lambda: self.outside_line_dropdown.set_selected(0))

    def _on_outside_dest_dropdown_selected(self, *args):
        idx = self.outside_dest_dropdown.get_selected()
        if idx > 0:
            model = self.outside_dest_dropdown.get_model()
            st = model.get_string(idx)
            self.outside_dest_entry.set_text(st)
            GLib.idle_add(lambda: self.outside_dest_dropdown.set_selected(0))

    def _on_outside_route_entry_changed(self, *args):
        if self._syncing_route:
            return
        self._syncing_route = True
        ln = self.outside_line_entry.get_text().strip()
        dest = self.outside_dest_entry.get_text().strip()

        line_model = self.first_line_row.get_model()
        if line_model and ln:
            for i in range(line_model.get_n_items()):
                if line_model.get_string(i) == ln:
                    self.first_line_row.set_selected(i)
                    break

        dest_model = self.first_dest_row.get_model()
        if dest_model and dest:
            for i in range(dest_model.get_n_items()):
                if dest_model.get_string(i) == dest:
                    self.first_dest_row.set_selected(i)
                    self.terminus_station_row.set_selected(i)
                    break

        self._syncing_route = False
        self._update_bottom_route_label()

    def _on_first_route_combo_changed(self, *args):
        if self._syncing_route:
            return
        self._syncing_route = True
        ln = self._get_row_selected_text(self.first_line_row)
        dest = self._get_row_selected_text(self.first_dest_row)
        if ln:
            self.outside_line_entry.set_text(ln)
        if dest:
            self.outside_dest_entry.set_text(dest)
        self._syncing_route = False
        self._update_bottom_route_label()

    def _update_bottom_route_label(self):
        ln = self.outside_line_entry.get_text().strip() or self._get_row_selected_text(self.first_line_row) or "未设线路"
        dest = self.outside_dest_entry.get_text().strip() or self._get_row_selected_text(self.first_dest_row) or "未设终点"
        self.bottom_route_label.set_text(f"当前线路：{ln} · 开往 {dest}")

    def _on_arrive_sync_clicked(self, *args):
        st = self.depart_station_entry.get_text().strip()
        if st:
            self.arrive_station_entry.set_text(st)
            # 若出站开启了“下一站是终点站”，自动同步开启到站的“本站是终点站”开关
            next_term_row = self._switch_widgets.get("is_terminus_next")
            arr_term_row = self._switch_widgets.get("is_terminus_arrive")
            if next_term_row and arr_term_row and next_term_row.get_active():
                arr_term_row.set_active(True)
            self._show_toast(f"已同步到达站点：{st}")
        else:
            self._show_toast("出站下一站目前为空")

    def _on_transfer_switch_toggled(self, *args):
        self._update_transfer_expander_subtitle()

    def _update_transfer_expander_subtitle(self):
        selected = [line for line, row in self._transfer_switch_widgets.items() if row.get_active()]
        if selected:
            self.depart_transfer_expander.set_subtitle("换乘：" + "、".join(selected))
        else:
            self.depart_transfer_expander.set_subtitle("无换乘")

    def _on_mute_clicked(self, *args):
        muted = self.player.toggle_mute()
        icon = "audio-volume-muted-symbolic" if muted else "audio-volume-high-symbolic"
        tip = "取消静音" if muted else "静音"
        self.bottom_mute_btn.set_icon_name(icon)
        self.bottom_mute_btn.set_tooltip_text(tip)

    def _collect_switch_states(self) -> Dict[str, bool]:
        return {sw_id: row.get_active() for sw_id, row in self._switch_widgets.items()}

    def _show_toast(self, text: str):
        toast = Adw.Toast.new(text)
        self.toast_overlay.add_toast(toast)

    def _show_station_not_found(self, station_name: str):
        heading = "未收录该站点"
        body = (
            f"当前语音包中尚未收录「{station_name}」的报站录音。\n\n"
            f"如果刚刚剪辑放入了音频，可点击左上角的刷新按钮重新加载！"
        )
        if hasattr(Adw, "AlertDialog"):
            dlg = Adw.AlertDialog(heading=heading, body=body)
            dlg.add_response("ok", "知道了")
            dlg.present(self)
        elif hasattr(Adw, "MessageDialog"):
            dlg = Adw.MessageDialog(transient_for=self, heading=heading, body=body)
            dlg.add_response("ok", "知道了")
            dlg.present()
        else:
            self._show_toast(f"未收录站点：{station_name}")

    def _show_line_not_found(self, line_name: str):
        heading = "未收录该线路"
        body = (
            f"当前语音包中尚未收录「{line_name}」的线路名录音。\n\n"
            f"如果刚刚剪辑放入了音频，可点击左上角的刷新按钮重新加载！"
        )
        if hasattr(Adw, "AlertDialog"):
            dlg = Adw.AlertDialog(heading=heading, body=body)
            dlg.add_response("ok", "知道了")
            dlg.present(self)
        elif hasattr(Adw, "MessageDialog"):
            dlg = Adw.MessageDialog(transient_for=self, heading=heading, body=body)
            dlg.add_response("ok", "知道了")
            dlg.present()
        else:
            self._show_toast(f"未收录线路：{line_name}")

    def _play_rel_single(self, label: str, rel_file: str, channel: str = "inside"):
        f = self.pack_manager.resolve_rel_file(rel_file)
        if not f:
            self._show_toast(f"未找到音频：{rel_file}")
            return
        self.player.play_queue(f"单段播报：{label}", [AudioSegment(label, f)], channel=channel)

    def _on_depart_play(self, *args):
        st = self.depart_station_entry.get_text().strip()
        intro = self.depart_intro_entry.get_text().strip()
        if not st:
            self._show_toast("请输入或选择下一站站名")
            return

        if not self.pack_manager.get_station_audio(st):
            self._show_station_not_found(st)
            return

        if intro and intro not in ("无", "无介绍", "不插播", "不插播介绍"):
            if not self.pack_manager.get_intro_audio(intro):
                self._show_toast(f"未收录「{intro}」的站点介绍音频")
                return

        selected_transfers = [line for line, row in self._transfer_switch_widgets.items() if row.get_active()]
        segments = self.pack_manager.execute_pipeline(
            pipeline_name="depart",
            slots={"station": st, "transfer": selected_transfers, "intro": intro},
            switch_states=self._collect_switch_states(),
        )
        if not segments:
            self._show_toast("未找到可播放的音频切片")
            return
        self.player.play_queue(f"出站预告：下一站 {st}", segments, channel="inside")

    def _on_arrive_play(self, *args):
        st = self.arrive_station_entry.get_text().strip()
        if not st:
            self._show_toast("请输入或选择到达站点")
            return

        if not self.pack_manager.get_station_audio(st):
            self._show_station_not_found(st)
            return

        chime = self._get_row_selected_text(self.arrive_chime_row)
        ad = self._get_row_selected_text(self.arrive_ad_row)

        segments = self.pack_manager.execute_pipeline(
            pipeline_name="arrive",
            slots={"station": st, "chime": chime, "ad": ad},
            switch_states=self._collect_switch_states(),
        )
        if not segments:
            self._show_toast("未找到可播放的音频切片")
            return
        is_term = bool(
            self._switch_widgets.get("is_terminus_arrive")
            and self._switch_widgets["is_terminus_arrive"].get_active()
        )
        prefix = "终点站到达" if is_term else "进站广播"
        self.player.play_queue(f"{prefix}：{st}", segments, channel="inside")

    def _on_first_play(self, *args):
        line = self._get_row_selected_text(self.first_line_row)
        origin = self._get_row_selected_text(self.first_origin_row)
        dest = self._get_row_selected_text(self.first_dest_row)

        segments = self.pack_manager.execute_pipeline(
            pipeline_name="first_station",
            slots={"line": line, "origin": origin, "destination": dest},
            switch_states=self._collect_switch_states(),
        )
        if not segments:
            self._show_toast("未找到可播放的音频切片")
            return
        self.player.play_queue(f"始发站启程：{line}", segments, channel="inside")

    def _on_terminus_play(self, *args):
        st = self._get_row_selected_text(self.terminus_station_row)
        chime = self._get_row_selected_text(self.arrive_chime_row)

        segments = self.pack_manager.execute_pipeline(
            pipeline_name="terminus",
            slots={"station": st, "chime": chime},
            switch_states=self._collect_switch_states(),
        )
        if not segments:
            self._show_toast("未找到可播放的音频切片")
            return
        self.player.play_queue(f"终点站到达：{st}", segments, channel="inside")

    def _on_outside_play(self, *args):
        line = self.outside_line_entry.get_text().strip()
        dest = self.outside_dest_entry.get_text().strip()

        if not line:
            self._show_toast("请输入或选择当前运行线路")
            return
        if not self.pack_manager.get_line_audio(line):
            self._show_line_not_found(line)
            return

        if not dest:
            self._show_toast("请输入或选择开往终点站")
            return
        if not self.pack_manager.get_station_audio(dest):
            self._show_station_not_found(dest)
            return

        segments = self.pack_manager.execute_pipeline(
            pipeline_name="outside",
            slots={"line": line, "destination": dest},
            switch_states=self._collect_switch_states(),
        )
        if not segments:
            self._show_toast("未找到可播放的音频切片")
            return
        self.player.play_queue(f"车外进站广播：{line}（开往 {dest}）", segments, channel="outside")

    def open_preferences_dialog(self):
        """打开首选项窗口（设置内报与外报输出扬声器）"""
        if hasattr(Adw, "PreferencesDialog"):
            dlg = Adw.PreferencesDialog(title="首选项")
            is_dialog = True
        else:
            dlg = Adw.PreferencesWindow(title="首选项", transient_for=self, modal=True)
            is_dialog = False

        page = Adw.PreferencesPage(title="音频与扬声器", icon_name="audio-speakers-symbolic")
        audio_group = Adw.PreferencesGroup(
            title="内外报扬声器通道分离",
            description="可分别指定车内报站（内报）与车外进站广播（外报）的输出设备，实现车内与车外喇叭独立发声",
        )

        inside_row = Adw.ComboRow(
            title="车内广播扬声器（内报）",
            subtitle="用于日常出站、到站、始发与终点站等车厢内广播",
        )
        inside_test_btn = Gtk.Button(
            label="试听内报",
            icon_name="media-playback-start-symbolic",
            valign=Gtk.Align.CENTER,
        )
        inside_row.add_suffix(inside_test_btn)

        outside_row = Adw.ComboRow(
            title="车外广播扬声器（外报）",
            subtitle="用于车外进站广播（可外接蓝牙音箱或第二声卡模拟车外大喇叭）",
        )
        outside_test_btn = Gtk.Button(
            label="试听外报",
            icon_name="audio-volume-high-symbolic",
            valign=Gtk.Align.CENTER,
        )
        outside_row.add_suffix(outside_test_btn)

        refresh_row = Adw.ActionRow(
            title="重新扫描音频设备",
            subtitle="接入新的蓝牙音箱、耳机或 USB 声卡后点击刷新列表",
        )
        refresh_btn = Gtk.Button(
            label="刷新列表",
            icon_name="view-refresh-symbolic",
            valign=Gtk.Align.CENTER,
        )
        refresh_row.add_suffix(refresh_btn)

        audio_group.add(inside_row)
        audio_group.add(outside_row)
        audio_group.add(refresh_row)
        page.add(audio_group)
        dlg.add(page)

        state = {"updating": False, "devices": []}

        def _populate_devices():
            state["updating"] = True
            devs = self.player.list_output_devices()
            state["devices"] = devs
            names = [d["name"] for d in devs]
            inside_row.set_model(Gtk.StringList.new(names))
            outside_row.set_model(Gtk.StringList.new(names))

            in_idx = 0
            out_idx = 0
            for i, d in enumerate(devs):
                if d["id"] == self.player.inside_device_id:
                    in_idx = i
                if d["id"] == self.player.outside_device_id:
                    out_idx = i
            inside_row.set_selected(in_idx)
            outside_row.set_selected(out_idx)
            state["updating"] = False

        def _on_inside_changed(*_args):
            if state["updating"]:
                return
            idx = inside_row.get_selected()
            if idx < len(state["devices"]):
                self.player.inside_device_id = state["devices"][idx]["id"]
                self.player.save_preferences()

        def _on_outside_changed(*_args):
            if state["updating"]:
                return
            idx = outside_row.get_selected()
            if idx < len(state["devices"]):
                self.player.outside_device_id = state["devices"][idx]["id"]
                self.player.save_preferences()

        def _on_test_inside(*_args):
            self._play_rel_single("内报扬声器测试", "站前广播/车辆启动，请扶好坐好", channel="inside")

        def _on_test_outside(*_args):
            self._play_rel_single("外报扬声器测试", "外报/车辆进站，请在道沿上等候，注意安全", channel="outside")

        inside_row.connect("notify::selected", _on_inside_changed)
        outside_row.connect("notify::selected", _on_outside_changed)
        inside_test_btn.connect("clicked", _on_test_inside)
        outside_test_btn.connect("clicked", _on_test_outside)
        refresh_btn.connect("clicked", lambda *_: _populate_devices())

        _populate_devices()

        if is_dialog:
            dlg.present(self)
        else:
            dlg.present()

    # 播放器回调
    def _on_segment_start(self, title: str, idx: int, total: int, seg_name: str):
        def _update():
            channel_tag = "外报扬声器" if self.player.current_channel == "outside" else "内报扬声器"
            self.bottom_title_label.set_text(title)
            self.bottom_subtitle_label.set_text(f"[{channel_tag}] 正在播放：{seg_name}")
            self.bottom_counter_label.set_text(f"{idx + 1} / {total}")
            fraction = (idx + 1) / total if total > 0 else 0.0
            self.bottom_progress.set_fraction(fraction)

            self.bottom_pause_btn.set_icon_name("media-playback-pause-symbolic")
            self.bottom_pause_btn.set_sensitive(True)
            self.bottom_skip_btn.set_sensitive(True)
            self.bottom_stop_btn.set_sensitive(True)
            return False

        GLib.idle_add(_update)

    def _on_pause_changed(self, is_paused: bool):
        def _update():
            if is_paused:
                self.bottom_pause_btn.set_icon_name("media-playback-start-symbolic")
                cur = self.bottom_subtitle_label.get_text()
                if not cur.endswith("（已暂停）"):
                    self.bottom_subtitle_label.set_text(f"{cur}（已暂停）")
            else:
                self.bottom_pause_btn.set_icon_name("media-playback-pause-symbolic")
                cur = self.bottom_subtitle_label.get_text()
                if cur.endswith("（已暂停）"):
                    self.bottom_subtitle_label.set_text(cur[:-5])
            return False

        GLib.idle_add(_update)

    def _on_playback_finished(self):
        def _update():
            self.bottom_title_label.set_text("空闲就绪")
            self.bottom_subtitle_label.set_text("播报完成")
            self.bottom_counter_label.set_text("")
            self.bottom_progress.set_fraction(1.0)

            self.bottom_pause_btn.set_icon_name("media-playback-pause-symbolic")
            self.bottom_pause_btn.set_sensitive(False)
            self.bottom_skip_btn.set_sensitive(False)
            self.bottom_stop_btn.set_sensitive(False)
            return False

        GLib.idle_add(_update)

    def _on_playback_error(self, err_msg: str):
        def _update():
            self._show_toast(f"播放发生错误: {err_msg}")
            return False

        GLib.idle_add(_update)
