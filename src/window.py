# window.py
#
# Copyright 2026 MM 喵了个
#
# SPDX-License-Identifier: LGPL-3.0-or-later

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from gettext import gettext as _
from gi.repository import Adw, Gtk, GLib, Gio
from .engine import PackManager, AudioPlayer, AudioSegment


@Gtk.Template(resource_path='/com/github/mimiaomc/nextstop/window.ui')
class NextstopWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'NextstopWindow'

    # 顶栏与主容器
    pack_dropdown = Gtk.Template.Child()
    import_pack_btn = Gtk.Template.Child()
    refresh_pack_btn = Gtk.Template.Child()
    switcher_title = Gtk.Template.Child()
    main_stack = Gtk.Template.Child()
    view_stack = Gtk.Template.Child()
    toast_overlay = Gtk.Template.Child()

    # 空状态页
    empty_status_page = Gtk.Template.Child()
    empty_import_btn = Gtk.Template.Child()
    empty_open_folder_btn = Gtk.Template.Child()

    # 出站 / 下一站
    depart_group = Gtk.Template.Child()
    depart_station_entry = Gtk.Template.Child()
    depart_station_dropdown = Gtk.Template.Child()
    depart_intro_entry = Gtk.Template.Child()
    depart_intro_clear_btn = Gtk.Template.Child()
    depart_intro_dropdown = Gtk.Template.Child()
    depart_transfer_expander = Gtk.Template.Child()
    depart_ad_row = Gtk.Template.Child()

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
    bottom_player_bar = Gtk.Template.Child()
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

        self._setup_actions()
        self._setup_signals()
        self._populate_pack_dropdown()
        self._rebuild_pack_ui()

    def _setup_actions(self):
        for act_name, callback in [
            ("import_pack", self._on_import_pack_clicked),
            ("open_packs_dir", self._on_open_packs_dir_clicked),
            ("delete_pack", self._on_delete_pack_clicked),
        ]:
            action = Gio.SimpleAction.new(act_name, None)
            action.connect("activate", callback)
            self.add_action(action)

    def _get_row_selected_text(self, row: Adw.ComboRow) -> str:
        idx = row.get_selected()
        model = row.get_model()
        if model and idx < model.get_n_items():
            return model.get_string(idx)
        return ""

    def _populate_pack_dropdown(self):
        self._updating_packs = True
        if self.pack_manager.available_packs:
            pack_names = [p.name for p in self.pack_manager.available_packs]
            self.pack_dropdown.set_model(Gtk.StringList.new(pack_names))
            if self.pack_manager.current_pack:
                for i, p in enumerate(self.pack_manager.available_packs):
                    if p.id == self.pack_manager.current_pack.id:
                        self.pack_dropdown.set_selected(i)
                        break
        else:
            self.pack_dropdown.set_model(Gtk.StringList.new([_("No pack imported")]))
            self.pack_dropdown.set_selected(0)
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

        has_packs = bool(self.pack_manager.available_packs and self.pack_manager.current_pack)
        self.main_stack.set_visible_child_name("content" if has_packs else "empty")
        self.switcher_title.set_view_switcher_enabled(has_packs)
        self.switcher_title.set_title(_("NextStop Broadcaster") if has_packs else "NextStop")
        self.pack_dropdown.set_sensitive(has_packs)
        self.bottom_player_bar.set_visible(has_packs)

        if not has_packs:
            return

        stations = self.pack_manager.stations or []
        picker_items = [_("Select from library...")] + stations
        self.depart_station_dropdown.set_model(Gtk.StringList.new(picker_items))
        self.arrive_station_dropdown.set_model(Gtk.StringList.new(picker_items))
        self.outside_dest_dropdown.set_model(Gtk.StringList.new(picker_items))
        self.depart_station_dropdown.set_selected(0)
        self.arrive_station_dropdown.set_selected(0)
        self.outside_dest_dropdown.set_selected(0)

        intros = self.pack_manager.intros or []
        intro_picker_items = [_("Select from library..."), _("No intro")] + intros
        self.depart_intro_dropdown.set_model(Gtk.StringList.new(intro_picker_items))
        self.depart_intro_dropdown.set_selected(0)
        self.depart_intro_entry.set_text("")

        self.first_origin_row.set_model(Gtk.StringList.new(stations))
        self.first_dest_row.set_model(Gtk.StringList.new(stations))
        self.terminus_station_row.set_model(Gtk.StringList.new(stations))

        # 构建换乘线路多选开关
        transfer_list = [t for t in self.pack_manager.transfers if t and t not in (_("No transfer"), "无换乘")]
        for line_name in transfer_list:
            row = Adw.SwitchRow(title=line_name, active=False)
            row.connect("notify::active", self._on_transfer_switch_toggled)
            self.depart_transfer_expander.add_row(row)
            self._dynamic_transfer_rows.append(row)
            self._transfer_switch_widgets[line_name] = row
        self._update_transfer_expander_subtitle()

        self.arrive_chime_row.set_model(Gtk.StringList.new(self.pack_manager.chimes))
        self.arrive_chime_row.set_selected(0)

        self.depart_ad_row.set_model(Gtk.StringList.new(self.pack_manager.ads))
        self.arrive_ad_row.set_model(Gtk.StringList.new(self.pack_manager.ads))

        lines = self.pack_manager.lines or []
        line_picker_items = [_("Select from library...")] + lines
        self.outside_line_dropdown.set_model(Gtk.StringList.new(line_picker_items))
        self.outside_line_dropdown.set_selected(0)
        self.first_line_row.set_model(Gtk.StringList.new(lines))

        # 读取 pack.json 默认值
        defaults = self.pack_manager.config.get("defaults", {})
        def_station = defaults.get("station") or (stations[0] if stations else "")
        def_origin = defaults.get("origin") or (stations[0] if stations else "")
        def_dest = defaults.get("destination") or (stations[-1] if len(stations) > 1 else (stations[0] if stations else ""))
        def_line = defaults.get("line") or (lines[0] if lines else "")

        self._syncing_route = True
        self.depart_station_entry.set_text(def_station)
        self.arrive_station_entry.set_text(def_station)
        self.outside_dest_entry.set_text(def_dest)
        self.outside_line_entry.set_text(def_line)

        for i, s in enumerate(stations):
            if def_origin and (def_origin == s or def_origin in s):
                self.first_origin_row.set_selected(i)
                break
        for i, s in enumerate(stations):
            if def_dest and (def_dest == s or def_dest in s):
                self.first_dest_row.set_selected(i)
                self.terminus_station_row.set_selected(i)
                break
        for i, ln in enumerate(lines):
            if def_line and (def_line == ln or def_line in ln):
                self.first_line_row.set_selected(i)
                break
        self._syncing_route = False
        self._update_bottom_route_label()

        # 1. 动态生成出站卡片开关
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
            title=_("Play Depart Broadcast"),
            subtitle=_("Assemble and play departure audio queue according to pack rules"),
        )
        dep_btn = Gtk.Button(
            label=_("Start Trip"),
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
            title=_("Play Arrival Broadcast"),
            subtitle=_("Chime - Commercial - Arrival - Safety reminder"),
        )
        arr_btn = Gtk.Button(
            label=_("Arrive Stop"),
            icon_name="media-playback-start-symbolic",
            valign=Gtk.Align.CENTER,
            css_classes=["suggested-action"],
        )
        arr_btn.connect("clicked", self._on_arrive_play)
        arr_action.add_suffix(arr_btn)
        self.arrive_group.add(arr_action)
        self._dynamic_arrive_rows.append(arr_action)

        # 4. 动态生成全局车型与特性开关
        global_switches = self.pack_manager.get_switches(placement="global")
        for sw_cfg in global_switches:
            row = Adw.SwitchRow(
                title=sw_cfg.get("title", ""),
                subtitle=sw_cfg.get("subtitle", ""),
                active=bool(sw_cfg.get("default", False)),
            )
            self.global_switches_group.add(row)
            self._dynamic_global_rows.append(row)
            self._switch_widgets[sw_cfg["id"]] = row

        if not global_switches:
            empty_row = Adw.ActionRow(
                title=_("No Global Feature Switches"),
                subtitle=_("Current pack has no global vehicle or system switches configured"),
                sensitive=False,
            )
            self.global_switches_group.add(empty_row)
            self._dynamic_global_rows.append(empty_row)

        # 5. 动态生成单项快捷口令列表
        quick_clips = self.pack_manager.get_quick_clips()
        for clip in quick_clips:
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

        if not quick_clips:
            empty_row = Adw.ActionRow(
                title=_("No Quick Clips"),
                subtitle=_("Current pack has no quick clips configured"),
                sensitive=False,
            )
            self.quick_clips_group.add(empty_row)
            self._dynamic_quick_rows.append(empty_row)

    def _setup_signals(self):
        """绑定按钮动作与播放器事件"""
        self.player.on_segment_start = self._on_segment_start
        self.player.on_pause_changed = self._on_pause_changed
        self.player.on_finished = self._on_playback_finished
        self.player.on_error = self._on_playback_error

        # 顶栏语音包切换、导入与热刷新
        self.pack_dropdown.connect("notify::selected", self._on_pack_selected)
        self.import_pack_btn.connect("clicked", self._on_import_pack_clicked)
        self.refresh_pack_btn.connect("clicked", self._on_refresh_pack_clicked)

        # 空状态页按钮
        self.empty_import_btn.connect("clicked", self._on_import_pack_clicked)
        self.empty_open_folder_btn.connect("clicked", self._on_open_packs_dir_clicked)

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
            self._show_toast(_("Switched pack: {name}").format(name=pack.name))

    def _on_import_pack_clicked(self, *args):
        filter_zip = Gtk.FileFilter()
        filter_zip.set_name(_("Announcement Pack (*.zip)"))
        filter_zip.add_pattern("*.zip")
        filter_zip.add_mime_type("application/zip")

        dialog = Gtk.FileChooserNative.new(
            title=_("Select Announcement Pack ZIP Archive"),
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
            accept_label=_("Import"),
            cancel_label=_("Cancel"),
        )
        dialog.add_filter(filter_zip)
        dialog.connect("response", self._on_import_dialog_response)
        dialog.show()

    def _on_import_dialog_response(self, dialog, response_id):
        if response_id == Gtk.ResponseType.ACCEPT:
            gfile = dialog.get_file()
            if gfile:
                path = gfile.get_path()
                if path:
                    self._handle_import_path(path)

    def _handle_import_path(self, path: str):
        ok, info = self.pack_manager.inspect_zip_pack(path)
        if not ok:
            err_msg = info.get("error", _("Cannot parse pack archive"))
            self._show_alert_dialog(_("Import Failed"), err_msg)
            return

        existing = info.get("existing")
        if not existing:
            # 新安装包，直接导入
            self._do_import_pack(path)
            return

        pack_name = info["name"]
        pack_id = info["id"]
        old_ver = info["existing_version"]
        new_ver = info["version"]
        cmp_res = info["cmp"]

        if cmp_res > 0:
            heading = _("Update Announcement Pack?")
            body = _("An announcement pack '{name}' ({id}) is already installed.\n\nCurrent version: {old_ver}\nNew version: {new_ver}\n\nDo you want to update to the new version?").format(
                name=pack_name, id=pack_id, old_ver=old_ver, new_ver=new_ver
            )
            action_id = "update"
            action_label = _("Update")
            appearance = Adw.ResponseAppearance.SUGGESTED
        elif cmp_res == 0:
            heading = _("Reinstall Announcement Pack?")
            body = _("Announcement pack '{name}' ({id}) is already installed with the same version ({ver}).\n\nDo you want to overwrite and reinstall it?").format(
                name=pack_name, id=pack_id, ver=new_ver
            )
            action_id = "reinstall"
            action_label = _("Reinstall")
            appearance = Adw.ResponseAppearance.DEFAULT
        else:
            heading = _("Downgrade Announcement Pack?")
            body = _("The installed announcement pack '{name}' ({id}) has a newer version ({old_ver}) than the archive ({new_ver}).\n\nDo you really want to downgrade?").format(
                name=pack_name, id=pack_id, old_ver=old_ver, new_ver=new_ver
            )
            action_id = "downgrade"
            action_label = _("Downgrade")
            appearance = Adw.ResponseAppearance.DESTRUCTIVE

        if hasattr(Adw, "AlertDialog"):
            alert = Adw.AlertDialog(heading=heading, body=body)
            alert.add_response("cancel", _("Cancel"))
            alert.add_response(action_id, action_label)
            alert.set_response_appearance(action_id, appearance)

            def _on_confirm(_d, resp):
                if resp == action_id:
                    self._do_import_pack(path)

            alert.choose(self, None, _on_confirm)
        elif hasattr(Adw, "MessageDialog"):
            alert = Adw.MessageDialog.new(self, heading, body)
            alert.add_response("cancel", _("Cancel"))
            alert.add_response(action_id, action_label)
            alert.set_response_appearance(action_id, appearance)

            def _on_resp(_d, resp):
                if resp == action_id:
                    self._do_import_pack(path)

            alert.connect("response", _on_resp)
            alert.present()
        else:
            self._do_import_pack(path)

    def _do_import_pack(self, path: str):
        success, pack_id, msg = self.pack_manager.import_zip_pack(path)
        if success:
            self._show_toast(msg)
            self._populate_pack_dropdown()
            self._rebuild_pack_ui()
        else:
            self._show_alert_dialog(_("Import Failed"), msg)

    def _show_alert_dialog(self, heading: str, body: str):
        if hasattr(Adw, "AlertDialog"):
            alert = Adw.AlertDialog(heading=heading, body=body)
            alert.add_response("ok", _("OK"))
            alert.present(self)
        elif hasattr(Adw, "MessageDialog"):
            alert = Adw.MessageDialog.new(self, heading, body)
            alert.add_response("ok", _("OK"))
            alert.present()
        else:
            self._show_toast(f"{heading}: {body}")

    def _on_open_packs_dir_clicked(self, *args):
        packs_dir = self.pack_manager.get_user_packs_dir()
        uri = GLib.filename_to_uri(packs_dir)
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except Exception as e:
            self._show_toast(_("Failed to open directory: {err}").format(err=e))

    def _on_delete_pack_clicked(self, *args):
        self.open_manage_packs_dialog()

    def open_manage_packs_dialog(self):
        """打开类似首选项的二级弹窗，显示已安装报站包并支持逐一删除"""
        if hasattr(Adw, "PreferencesDialog"):
            dlg = Adw.PreferencesDialog(title=_("Delete Packs"))
            is_dialog = True
        else:
            dlg = Adw.PreferencesWindow(title=_("Delete Packs"), transient_for=self, modal=True)
            is_dialog = False

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title=_("Installed Announcement Packs"),
            description=_("View and delete imported transit announcement packs"),
        )
        page.add(group)
        dlg.add(page)

        dynamic_rows = []

        def _rebuild_group():
            for r in dynamic_rows:
                group.remove(r)
            dynamic_rows.clear()

            packs = self.pack_manager.available_packs
            if not packs:
                empty_row = Adw.ActionRow(
                    title=_("No announcement packs installed"),
                    subtitle=_("Import a .zip pack to get started"),
                    icon_name="package-x-generic-symbolic",
                )
                group.add(empty_row)
                dynamic_rows.append(empty_row)
                return

            for pack in packs:
                row = Adw.ActionRow(title=pack.name)
                is_current = bool(self.pack_manager.current_pack and self.pack_manager.current_pack.id == pack.id)

                sub_parts = [f"v{pack.version}"]
                if pack.city:
                    sub_parts.append(pack.city)
                if pack.system_type:
                    sub_parts.append(pack.system_type)
                if is_current:
                    sub_parts.append(_("Currently In Use"))
                row.set_subtitle(" • ".join(sub_parts))

                del_btn = Gtk.Button(
                    icon_name="user-trash-symbolic",
                    valign=Gtk.Align.CENTER,
                    tooltip_text=_("Delete this pack"),
                )
                del_btn.add_css_class("flat")
                del_btn.add_css_class("destructive-action")
                del_btn.connect("clicked", lambda _b, p=pack: _on_confirm_delete(p))
                row.add_suffix(del_btn)
                group.add(row)
                dynamic_rows.append(row)

        def _on_confirm_delete(pack):
            heading = _("Delete Pack '{name}'?").format(name=pack.name)
            body = _("Are you sure you want to permanently delete announcement pack '{name}' ({id})? This action cannot be undone.").format(
                name=pack.name, id=pack.id
            )

            if hasattr(Adw, "AlertDialog"):
                alert = Adw.AlertDialog(heading=heading, body=body)
                alert.add_response("cancel", _("Cancel"))
                alert.add_response("delete", _("Delete"))
                alert.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

                def _alert_done(_d, resp):
                    if resp == "delete":
                        _execute_delete(pack)

                alert.choose(dlg, None, _alert_done)
            elif hasattr(Adw, "MessageDialog"):
                alert = Adw.MessageDialog.new(dlg if not is_dialog else self, heading, body)
                alert.add_response("cancel", _("Cancel"))
                alert.add_response("delete", _("Delete"))
                alert.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

                def _on_resp(_d, resp):
                    if resp == "delete":
                        _execute_delete(pack)

                alert.connect("response", _on_resp)
                alert.present()

        def _execute_delete(pack):
            ok, msg = self.pack_manager.delete_pack(pack.id)
            if ok:
                self._show_toast(_("Deleted pack: {name}").format(name=pack.name))
                self._populate_pack_dropdown()
                self._rebuild_pack_ui()
                _rebuild_group()
            else:
                self._show_toast(msg)

        _rebuild_group()

        if is_dialog:
            dlg.present(self)
        else:
            dlg.present()

    def _on_refresh_pack_clicked(self, *args):
        self.pack_manager.reload_current_pack()
        self._populate_pack_dropdown()
        self._rebuild_pack_ui()
        if self.pack_manager.available_packs:
            self._show_toast(_("Library refreshed ({n} stations)").format(n=len(self.pack_manager.stations)))
        else:
            self._show_toast(_("Library refreshed, no packs detected"))

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
        ln = self.outside_line_entry.get_text().strip() or self._get_row_selected_text(self.first_line_row) or _("Unset Route")
        dest = self.outside_dest_entry.get_text().strip() or self._get_row_selected_text(self.first_dest_row) or _("Unset Destination")
        self.bottom_route_label.set_text(_("Current Route: {line} · Bound for {dest}").format(line=ln, dest=dest))

    def _on_arrive_sync_clicked(self, *args):
        st = self.depart_station_entry.get_text().strip()
        if st:
            self.arrive_station_entry.set_text(st)
            # 若出站开启了“下一站是终点站”，自动同步开启到站的“本站是终点站”开关
            next_term_row = self._switch_widgets.get("is_terminus_next")
            arr_term_row = self._switch_widgets.get("is_terminus_arrive")
            if next_term_row and arr_term_row and next_term_row.get_active():
                arr_term_row.set_active(True)
            self._show_toast(_("Synchronized arrival station: {name}").format(name=st))
        else:
            self._show_toast(_("Next station field is currently empty"))

    def _on_transfer_switch_toggled(self, *args):
        self._update_transfer_expander_subtitle()

    def _update_transfer_expander_subtitle(self):
        selected = [line for line, row in self._transfer_switch_widgets.items() if row.get_active()]
        if selected:
            self.depart_transfer_expander.set_subtitle(_("Transfers: {list}").format(list=", ".join(selected)))
        else:
            self.depart_transfer_expander.set_subtitle(_("No transfer"))

    def _on_mute_clicked(self, *args):
        muted = self.player.toggle_mute()
        icon = "audio-volume-muted-symbolic" if muted else "audio-volume-high-symbolic"
        tip = _("Unmute") if muted else _("Mute")
        self.bottom_mute_btn.set_icon_name(icon)
        self.bottom_mute_btn.set_tooltip_text(tip)

    def _collect_switch_states(self) -> Dict[str, bool]:
        return {sw_id: row.get_active() for sw_id, row in self._switch_widgets.items()}

    def _show_toast(self, text: str):
        toast = Adw.Toast.new(text)
        self.toast_overlay.add_toast(toast)

    def _show_station_not_found(self, station_name: str):
        heading = _("Station Not Recorded")
        body = (
            _("Audio recording for station \"{name}\" is not found in the current pack.\n\n"
              "If you just added the audio file, click the Refresh button on the top left to reload!").format(name=station_name)
        )
        if hasattr(Adw, "AlertDialog"):
            dlg = Adw.AlertDialog(heading=heading, body=body)
            dlg.add_response("ok", _("OK"))
            dlg.present(self)
        elif hasattr(Adw, "MessageDialog"):
            dlg = Adw.MessageDialog(transient_for=self, heading=heading, body=body)
            dlg.add_response("ok", _("OK"))
            dlg.present()
        else:
            self._show_toast(_("Station not recorded: {name}").format(name=station_name))

    def _show_line_not_found(self, line_name: str):
        heading = _("Route Not Recorded")
        body = (
            _("Audio recording for route \"{name}\" is not found in the current pack.\n\n"
              "If you just added the audio file, click the Refresh button on the top left to reload!").format(name=line_name)
        )
        if hasattr(Adw, "AlertDialog"):
            dlg = Adw.AlertDialog(heading=heading, body=body)
            dlg.add_response("ok", _("OK"))
            dlg.present(self)
        elif hasattr(Adw, "MessageDialog"):
            dlg = Adw.MessageDialog(transient_for=self, heading=heading, body=body)
            dlg.add_response("ok", _("OK"))
            dlg.present()
        else:
            self._show_toast(_("Route not recorded: {name}").format(name=line_name))

    def _play_rel_single(self, label: str, rel_file: str, channel: str = "inside"):
        f = self.pack_manager.resolve_rel_file(rel_file)
        if not f:
            self._show_toast(_("Audio file not found: {file}").format(file=rel_file))
            return
        self.player.play_queue(_("Single Broadcast: {label}").format(label=label), [AudioSegment(label, f)], channel=channel)

    def _on_depart_play(self, *args):
        st = self.depart_station_entry.get_text().strip()
        intro = self.depart_intro_entry.get_text().strip()
        if not st:
            self._show_toast(_("Please enter or select the next station name"))
            return

        if not self.pack_manager.get_station_audio(st):
            self._show_station_not_found(st)
            return

        if intro and intro not in ("无", "无介绍", "不插播", "不插播介绍"):
            if not self.pack_manager.get_intro_audio(intro):
                self._show_toast(_("Feature intro audio not recorded: {name}").format(name=intro))
                return

        selected_transfers = [line for line, row in self._transfer_switch_widgets.items() if row.get_active()]
        ad = self._get_row_selected_text(self.depart_ad_row)
        segments = self.pack_manager.execute_pipeline(
            pipeline_name="depart",
            slots={"station": st, "transfer": selected_transfers, "intro": intro, "ad": ad},
            switch_states=self._collect_switch_states(),
        )
        if not segments:
            self._show_toast(_("No playable audio segments found"))
            return
        self.player.play_queue(_("Depart Alert: Next Station {name}").format(name=st), segments, channel="inside")

    def _on_arrive_play(self, *args):
        st = self.arrive_station_entry.get_text().strip()
        if not st:
            self._show_toast(_("Please enter or select the arrival station name"))
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
            self._show_toast(_("No playable audio segments found"))
            return
        is_term = bool(
            self._switch_widgets.get("is_terminus_arrive")
            and self._switch_widgets["is_terminus_arrive"].get_active()
        )
        prefix = _("Terminus Arrival") if is_term else _("Arrival Broadcast")
        self.player.play_queue(f"{prefix}: {st}", segments, channel="inside")

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
            self._show_toast(_("No playable audio segments found"))
            return
        self.player.play_queue(_("Origin Departure: {name}").format(name=line), segments, channel="inside")

    def _on_terminus_play(self, *args):
        st = self._get_row_selected_text(self.terminus_station_row)
        chime = self._get_row_selected_text(self.arrive_chime_row)

        segments = self.pack_manager.execute_pipeline(
            pipeline_name="terminus",
            slots={"station": st, "chime": chime},
            switch_states=self._collect_switch_states(),
        )
        if not segments:
            self._show_toast(_("No playable audio segments found"))
            return
        self.player.play_queue(_("Terminus Arrival: {name}").format(name=st), segments, channel="inside")

    def _on_outside_play(self, *args):
        line = self.outside_line_entry.get_text().strip()
        dest = self.outside_dest_entry.get_text().strip()

        if not line:
            self._show_toast(_("Please enter or select the operating line"))
            return
        if not self.pack_manager.get_line_audio(line):
            self._show_line_not_found(line)
            return

        if not dest:
            self._show_toast(_("Please enter or select the destination station"))
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
            self._show_toast(_("No playable audio segments found"))
            return
        self.player.play_queue(_("Outside Arrival: {line} (Bound for {dest})").format(line=line, dest=dest), segments, channel="outside")

    def open_preferences_dialog(self):
        """打开首选项窗口（设置内报与外报输出扬声器）"""
        if hasattr(Adw, "PreferencesDialog"):
            dlg = Adw.PreferencesDialog(title=_("Preferences"))
            is_dialog = True
        else:
            dlg = Adw.PreferencesWindow(title=_("Preferences"), transient_for=self, modal=True)
            is_dialog = False

        page = Adw.PreferencesPage(title=_("Audio & Speakers"), icon_name="audio-speakers-symbolic")
        audio_group = Adw.PreferencesGroup(
            title=_("Speaker Output Routing"),
            description=_("Assign distinct audio output devices for inside vehicle announcements and outside loudspeaker"),
        )

        inside_row = Adw.ComboRow(
            title=_("Inside Vehicle Speaker"),
            subtitle=_("Used for daily depart, arrive, origin and terminus broadcasts"),
        )
        inside_test_btn = Gtk.Button(
            label=_("Test Inside"),
            icon_name="media-playback-start-symbolic",
            valign=Gtk.Align.CENTER,
        )
        inside_row.add_suffix(inside_test_btn)

        outside_row = Adw.ComboRow(
            title=_("Outside Loudspeaker"),
            subtitle=_("Used for external arrival broadcasts (connect an external Bluetooth speaker or secondary sound card)"),
        )
        outside_test_btn = Gtk.Button(
            label=_("Test Outside"),
            icon_name="audio-volume-high-symbolic",
            valign=Gtk.Align.CENTER,
        )
        outside_row.add_suffix(outside_test_btn)

        refresh_row = Adw.ActionRow(
            title=_("Rescan Audio Devices"),
            subtitle=_("Click to reload list after connecting new Bluetooth speakers, headphones or USB audio"),
        )
        refresh_btn = Gtk.Button(
            label=_("Refresh"),
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
            self._play_rel_single(_("Inside Speaker Test"), "站前广播/车辆启动，请扶好坐好", channel="inside")

        def _on_test_outside(*_args):
            self._play_rel_single(_("Outside Speaker Test"), "外报/车辆进站，请在道沿上等候，注意安全", channel="outside")

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
            channel_tag = _("Outside Speaker") if self.player.current_channel == "outside" else _("Inside Speaker")
            self.bottom_title_label.set_text(title)
            self.bottom_subtitle_label.set_text(_("[{channel}] Playing: {segment}").format(channel=channel_tag, segment=seg_name))
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
            paused_suffix = _(" (Paused)")
            if is_paused:
                self.bottom_pause_btn.set_icon_name("media-playback-start-symbolic")
                cur = self.bottom_subtitle_label.get_text()
                if not cur.endswith(paused_suffix):
                    self.bottom_subtitle_label.set_text(f"{cur}{paused_suffix}")
            else:
                self.bottom_pause_btn.set_icon_name("media-playback-pause-symbolic")
                cur = self.bottom_subtitle_label.get_text()
                if cur.endswith(paused_suffix):
                    self.bottom_subtitle_label.set_text(cur[:-len(paused_suffix)])
            return False

        GLib.idle_add(_update)

    def _on_playback_finished(self):
        def _update():
            self.bottom_title_label.set_text(_("Idle Ready"))
            self.bottom_subtitle_label.set_text(_("Playback finished"))
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
            self._show_toast(_("Playback error: {err}").format(err=err_msg))
            return False

        GLib.idle_add(_update)
