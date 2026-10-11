using System;
using System.Collections.Generic;

public sealed class Transfer
{
    public readonly string From;
    public readonly string To;
    public readonly long Amount;
    public Transfer(string from, string to, long amount) { From = from; To = to; Amount = amount; }
}
public sealed class JournalEntry
{
    public readonly string From;
    public readonly string To;
    public readonly long Amount;
    public JournalEntry(Transfer transfer) { From = transfer.From; To = transfer.To; Amount = transfer.Amount; }
}
public sealed class Ledger
{
    public readonly Dictionary<string, long> Balances = new Dictionary<string, long>(StringComparer.Ordinal);
    public readonly List<JournalEntry> Journal = new List<JournalEntry>();
    public long Version;
}
public sealed class TransferBatch
{
    public long Apply(Ledger ledger, IReadOnlyList<Transfer> transfers)
    {
        if (transfers.Count == 0) return ledger.Version;

        // Public request: later transfers use earlier staged credits; all checked work precedes commit.
        // 为什么要有它：按原余额预校验会拒绝有效链式入账，直接写账会在中途失败后留下部分状态。
        var stagedBalances = new Dictionary<string, long>(ledger.Balances, StringComparer.Ordinal);
        var stagedJournal = new List<JournalEntry>();
        foreach (var transfer in transfers)
        {
            if (transfer == null || transfer.From == null || transfer.To == null
                || transfer.Amount <= 0 || String.Equals(transfer.From, transfer.To, StringComparison.Ordinal)
                || !stagedBalances.TryGetValue(transfer.From, out var fromBalance)
                || !stagedBalances.TryGetValue(transfer.To, out var toBalance)
                || fromBalance < transfer.Amount)
                throw new InvalidOperationException("invalid transfer");

            stagedBalances[transfer.From] = checked(fromBalance - transfer.Amount);
            stagedBalances[transfer.To] = checked(toBalance + transfer.Amount);
            stagedJournal.Add(new JournalEntry(transfer));
        }
        var nextVersion = checked(ledger.Version + 1);

        // Public request: preserve the existing containers and journal entries, with one version increment.
        // 为什么要有它：替换字典或列表会破坏调用者持有的身份；先算版本可防止版本溢出后仍提交账目。
        foreach (var balance in stagedBalances)
            ledger.Balances[balance.Key] = balance.Value;
        ledger.Journal.AddRange(stagedJournal);
        ledger.Version = nextVersion;
        return ledger.Version;
    }
}
