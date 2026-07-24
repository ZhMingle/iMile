import unittest
from unittest import mock

import imile_dispatcher as dispatcher


class FakeEdit:
    def __init__(self, value):
        self.value = value

    def get_value(self):
        return self.value

    @property
    def iface_value(self):
        return self

    @property
    def CurrentValue(self):
        return self.value

    def window_text(self):
        return self.value


class StepClock:
    def __init__(self, step=0.25):
        self.value = -step
        self.step = step

    def __call__(self):
        self.value += self.step
        return self.value


def box_row(route_code, box_code, waybill_count=1):
    return dispatcher.BoxRow(
        row_key=f"{route_code}:{box_code}",
        route_code=route_code,
        box_code=box_code,
        waybill_count=waybill_count,
    )


def result_signature(rows):
    return (
        (0, len(rows)),
        tuple(
            (
                dispatcher.normalize_route_code(row.route_code),
                row.box_code,
                row.waybill_count,
            )
            for row in rows
        ),
    )


class SearchRouteStateTests(unittest.TestCase):
    def make_page(self):
        page = dispatcher.UIADispatchPage(
            window=object(),
            route_base="",
            config={
                "dc_dispatch_action_timeout_seconds": 8,
                "dc_dispatch_query_timeout_seconds": 8,
            },
        )
        page._require_active_dispatch = mock.Mock()
        return page

    def patch_search_dependencies(
        self,
        page,
        edit,
        signature,
        rows,
        *,
        loading=False,
        clock_step=0.25,
    ):
        def write_value(control, value, *_args, **_kwargs):
            control.value = value

        return (
            mock.patch.object(dispatcher, "_find_route_edit", return_value=edit),
            mock.patch.object(
                dispatcher,
                "_set_edit_text",
                side_effect=write_value,
            ),
            mock.patch.object(
                dispatcher,
                "_activate_text_action",
                return_value=True,
            ),
            mock.patch.object(
                page,
                "_stable_result_signature",
                return_value=signature,
            ),
            mock.patch.object(page, "_is_loading", return_value=loading),
            mock.patch.object(page, "read_route_rows", return_value=list(rows)),
            mock.patch.object(dispatcher.time, "sleep", return_value=None),
            mock.patch.object(
                dispatcher.time,
                "monotonic",
                side_effect=StepClock(clock_step),
            ),
        )

    def test_same_query_with_stable_results_reuses_rows_without_input_or_click(self):
        page = self.make_page()
        edit = FakeEdit("301")
        rows = [box_row("301", "B301", 10)]
        page._last_loaded_query = "301"
        page._last_result_signature = result_signature(rows)
        patches = self.patch_search_dependencies(
            page,
            edit,
            result_signature(rows),
            rows,
        )

        with patches[0], patches[1] as set_text, patches[2] as click_query, patches[
            3
        ], patches[4], patches[5], patches[6], patches[7]:
            result = page.search_routes("301")

        self.assertEqual(list(result), rows)
        set_text.assert_not_called()
        click_query.assert_not_called()

    def test_first_call_with_matching_input_still_submits_query(self):
        page = self.make_page()
        edit = FakeEdit("301")
        rows = [box_row("301", "B301", 10)]
        signature = result_signature(rows)
        loading_states = iter((False, True, False, False, False))

        def loading():
            return next(loading_states, False)

        patches = self.patch_search_dependencies(
            page,
            edit,
            signature,
            rows,
        )
        with (
            patches[0],
            patches[1] as set_text,
            patches[2] as click_query,
            patches[3],
            mock.patch.object(page, "_is_loading", side_effect=loading),
            patches[5],
            patches[6],
            patches[7],
        ):
            result = page.search_routes("301")

        self.assertEqual(list(result), rows)
        set_text.assert_not_called()
        click_query.assert_called_once()

    def test_changed_query_does_not_accept_repeated_old_signature(self):
        page = self.make_page()
        edit = FakeEdit("201")
        old_rows = [box_row("201", "B201", 11)]
        new_rows = [box_row("302", "B302", 22)]
        old_signature = result_signature(old_rows)
        new_signature = result_signature(new_rows)
        state = {
            "clicked": False,
            "polls_after_click": 0,
            "new_result": False,
        }

        def write_value(control, value, *_args, **_kwargs):
            control.value = value

        def click_query(*_args, **_kwargs):
            state["clicked"] = True
            return True

        def signature():
            if not state["clicked"]:
                return old_signature
            state["polls_after_click"] += 1
            if state["polls_after_click"] <= 2:
                return old_signature
            state["new_result"] = True
            return new_signature

        def rows():
            return list(new_rows if state["new_result"] else old_rows)

        with (
            mock.patch.object(dispatcher, "_find_route_edit", return_value=edit),
            mock.patch.object(
                dispatcher,
                "_set_edit_text",
                side_effect=write_value,
            ) as set_text,
            mock.patch.object(
                dispatcher,
                "_activate_text_action",
                side_effect=click_query,
            ) as activate,
            mock.patch.object(
                page,
                "_stable_result_signature",
                side_effect=signature,
            ) as signatures,
            mock.patch.object(page, "_is_loading", return_value=False),
            mock.patch.object(page, "read_route_rows", side_effect=rows),
            mock.patch.object(dispatcher.time, "sleep", return_value=None),
            mock.patch.object(
                dispatcher.time,
                "monotonic",
                side_effect=StepClock(),
            ),
        ):
            result = page.search_routes("302")

        self.assertEqual(list(result), new_rows)
        self.assertGreaterEqual(signatures.call_count, 3)
        set_text.assert_called_once()
        activate.assert_called_once()

    def test_changed_query_without_loading_or_signature_change_times_out(self):
        page = self.make_page()
        edit = FakeEdit("201")
        old_rows = [box_row("201", "B201", 11)]
        patches = self.patch_search_dependencies(
            page,
            edit,
            result_signature(old_rows),
            old_rows,
            loading=False,
            clock_step=1.0,
        )

        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[
            5
        ], patches[6], patches[7]:
            with self.assertRaises(RuntimeError):
                page.search_routes("302")

    def test_changed_query_with_unreadable_old_state_requires_loading(self):
        page = self.make_page()
        edit = FakeEdit("201")
        rows = [box_row("302", "B302", 22)]
        signature = result_signature(rows)
        signatures = iter((None, signature, signature, signature))

        with (
            mock.patch.object(dispatcher, "_find_route_edit", return_value=edit),
            mock.patch.object(
                dispatcher,
                "_set_edit_text",
                side_effect=lambda control, value, *_args, **_kwargs: setattr(
                    control,
                    "value",
                    value,
                ),
            ),
            mock.patch.object(
                dispatcher,
                "_activate_text_action",
                return_value=True,
            ),
            mock.patch.object(
                page,
                "_stable_result_signature",
                side_effect=lambda: next(signatures, signature),
            ),
            mock.patch.object(page, "_is_loading", return_value=False),
            mock.patch.object(page, "read_route_rows", return_value=rows),
            mock.patch.object(dispatcher.time, "sleep", return_value=None),
            mock.patch.object(
                dispatcher.time,
                "monotonic",
                side_effect=StepClock(1.0),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "稳定地加载"):
                page.search_routes("302")

    def test_loading_transition_allows_same_signature_after_query_change(self):
        page = self.make_page()
        edit = FakeEdit("201")
        rows = []
        signature = result_signature(rows)
        loading_states = iter((False, True, False, False, False))

        def loading():
            return next(loading_states, False)

        patches = self.patch_search_dependencies(
            page,
            edit,
            signature,
            rows,
        )
        with (
            patches[0],
            patches[1] as set_text,
            patches[2] as click_query,
            patches[3],
            mock.patch.object(page, "_is_loading", side_effect=loading) as loading_mock,
            patches[5],
            patches[6],
            patches[7],
        ):
            result = page.search_routes("302")

        self.assertEqual(list(result), [])
        self.assertGreaterEqual(loading_mock.call_count, 1)
        set_text.assert_called_once()
        click_query.assert_called_once()

    def test_refresh_routes_clicks_query_without_rewriting_input(self):
        page = self.make_page()
        page.route_base = "301"
        edit = FakeEdit("301")
        old_rows = [box_row("301", "OLD", 10)]
        new_rows = [box_row("301", "NEW", 10)]
        old_signature = result_signature(old_rows)
        new_signature = result_signature(new_rows)
        state = {"clicked": False}

        def click_query(*_args, **_kwargs):
            state["clicked"] = True
            return True

        def signature():
            return new_signature if state["clicked"] else old_signature

        with (
            mock.patch.object(dispatcher, "_find_route_edit", return_value=edit),
            mock.patch.object(dispatcher, "_set_edit_text") as set_text,
            mock.patch.object(
                dispatcher,
                "_activate_text_action",
                side_effect=click_query,
            ) as activate,
            mock.patch.object(
                page,
                "_stable_result_signature",
                side_effect=signature,
            ),
            mock.patch.object(page, "_is_loading", return_value=False),
            mock.patch.object(page, "read_route_rows", return_value=new_rows),
            mock.patch.object(dispatcher.time, "sleep", return_value=None),
            mock.patch.object(
                dispatcher.time,
                "monotonic",
                side_effect=StepClock(),
            ),
        ):
            result = page.refresh_routes()

        self.assertEqual(list(result), new_rows)
        set_text.assert_not_called()
        activate.assert_called_once_with(
            page.window,
            dispatcher.QUERY_KEYS,
            prefer_right=True,
        )


if __name__ == "__main__":
    unittest.main()
