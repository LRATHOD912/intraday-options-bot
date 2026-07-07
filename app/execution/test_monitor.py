from app.execution.monitor import check_exit_rules

def main():
    print("========== Monitor Dry Run ==========")
    tests = [
        ("Stop loss case", 2.00, 1.55),
        ("Take profit case", 2.00, 2.60),
        ("Hold case", 2.00, 2.10),
    ]

    for name, entry, current in tests:
        result = check_exit_rules(
            option_symbol="QQQ_PAPER_MONITOR_CHECK",
            entry_price=entry,
            current_price=current,
            qty=1,
        )
        print(f"\n{name}")
        print(result)


if __name__ == "__main__":
    main()
