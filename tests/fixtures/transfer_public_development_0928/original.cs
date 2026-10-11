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
        foreach (var transfer in transfers)
        {
            if (transfer.Amount <= 0 || transfer.From == transfer.To || !ledger.Balances.ContainsKey(transfer.From)
                || !ledger.Balances.ContainsKey(transfer.To) || ledger.Balances[transfer.From] < transfer.Amount)
                throw new InvalidOperationException("invalid transfer");
            ledger.Balances[transfer.From] = checked(ledger.Balances[transfer.From] - transfer.Amount);
            ledger.Balances[transfer.To] = checked(ledger.Balances[transfer.To] + transfer.Amount);
            ledger.Journal.Add(new JournalEntry(transfer));
        }
        ledger.Version = checked(ledger.Version + 1);
        return ledger.Version;
    }
}
