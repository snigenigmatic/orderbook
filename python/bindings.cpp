#include "orderbook/backtest.hpp"

#include <nanobind/nanobind.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

namespace nb = nanobind;
using namespace nb::literals;

NB_MODULE(_core, m)
{
    nb::enum_<Side>(m, "Side")
        .value("Bid", Side::Bid)
        .value("Ask", Side::Ask);

    nb::enum_<OwnStatus>(m, "OrderStatus")
        .value("Pending", OwnStatus::Pending)
        .value("Active", OwnStatus::Active)
        .value("Filled", OwnStatus::Filled)
        .value("Cancelled", OwnStatus::Cancelled)
        .value("Rejected", OwnStatus::Rejected);

    nb::class_<BacktestConfig>(m, "BacktestConfig")
        .def(nb::init<>())
        .def_rw("order_latency", &BacktestConfig::order_latency)
        .def_rw("bar_seconds", &BacktestConfig::bar_seconds)
        .def_rw("session_start", &BacktestConfig::session_start)
        .def_rw("session_end", &BacktestConfig::session_end)
        .def_rw("maker_rebate", &BacktestConfig::maker_rebate)
        .def_rw("reconcile", &BacktestConfig::reconcile);

    nb::class_<OwnOrder>(m, "OwnOrder")
        .def_ro("id", &OwnOrder::id)
        .def_ro("side", &OwnOrder::side)
        .def_ro("price", &OwnOrder::price)
        .def_ro("quantity", &OwnOrder::quantity)
        .def_ro("remaining", &OwnOrder::remaining)
        .def_ro("submitted_at", &OwnOrder::submitted_at)
        .def_ro("active_at", &OwnOrder::active_at)
        .def_ro("queue_at_entry", &OwnOrder::queue_at_entry)
        .def_ro("status", &OwnOrder::status)
        .def_ro("cancel_requested", &OwnOrder::cancel_requested);

    nb::class_<Fill>(m, "Fill")
        .def_ro("time", &Fill::time)
        .def_ro("order_id", &Fill::order_id)
        .def_ro("side", &Fill::side)
        .def_ro("price", &Fill::price)
        .def_ro("volume", &Fill::volume)
        .def_ro("queue_at_entry", &Fill::queue_at_entry)
        .def_ro("resting_seconds", &Fill::resting_seconds)
        .def_ro("mid_at_fill", &Fill::mid_at_fill);

    nb::class_<Backtester>(m, "Backtester")
        .def(nb::init<const std::string&, const std::string&, BacktestConfig>(),
             "message_path"_a, "orderbook_path"_a, "config"_a)
        .def("run_until", &Backtester::run_until, "t"_a, nb::call_guard<nb::gil_scoped_release>())
        .def("run_to_end", &Backtester::run_to_end, nb::call_guard<nb::gil_scoped_release>())
        .def("submit", &Backtester::submit, "side"_a, "price"_a, "quantity"_a)
        .def("cancel", &Backtester::cancel, "order_id"_a)
        .def("take_fills", &Backtester::take_fills)
        .def("open_orders", &Backtester::open_orders)
        .def("order", [](const Backtester& bt, OrderId id) -> nb::object
        {
            const OwnOrder* o = bt.order(id);
            return o ? nb::cast(*o) : nb::none();
        }, "order_id"_a)
        .def("queue_ahead", &Backtester::queue_ahead, "order_id"_a)
        .def("best_bid", [](const Backtester& bt) { return bt.book().best_bid(); })
        .def("best_ask", [](const Backtester& bt) { return bt.book().best_ask(); })
        .def("has_bid", [](const Backtester& bt) { return bt.book().has_bid(); })
        .def("has_ask", [](const Backtester& bt) { return bt.book().has_ask(); })
        .def("depth", [](const Backtester& bt, Side side, size_t levels) { return bt.book().depth(side, levels); },
             "side"_a, "levels"_a = 5)
        .def("mid", &Backtester::mid)
        .def_prop_ro("now", &Backtester::now)
        .def_prop_ro("done", &Backtester::done)
        .def_prop_ro("cursor", &Backtester::cursor)
        .def_prop_ro("message_count", &Backtester::message_count)
        .def_prop_ro("position", &Backtester::position)
        .def_prop_ro("cash", &Backtester::cash)
        .def_prop_ro("rebates", &Backtester::rebates)
        .def_prop_ro("traded_volume", &Backtester::traded_volume)
        .def("bars", [](const Backtester& bt)
        {
            const Bars& b = bt.bars();
            nb::dict d;
            d["end_time"] = b.end_time;
            d["mid"] = b.mid;
            d["spread"] = b.spread;
            d["realized_var"] = b.realized_var;
            d["ofi"] = b.ofi;
            d["volume"] = b.volume;
            d["trades"] = b.trades;
            d["imbalance"] = b.imbalance;
            return d;
        })
        .def("stats", [](const Backtester& bt)
        {
            const ReplayStats& s = bt.stats();
            nb::dict d;
            d["messages"] = s.messages;
            d["unknown_orders"] = s.unknown_orders;
            d["hidden_executions"] = s.hidden_executions;
            d["halts"] = s.halts;
            d["reconcile_events"] = s.reconcile_events;
            d["reconcile_levels"] = s.reconcile_levels;
            d["reconcile_volume"] = s.reconcile_volume;
            d["reconcile_by_level"] = s.reconcile_by_level;
            return d;
        });
}
