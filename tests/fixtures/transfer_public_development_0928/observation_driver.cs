using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;

public static class ObservationDriver
{
    static Transfer TransferOf(JsonElement item) => new Transfer(item.GetProperty("from").GetString(),
        item.GetProperty("to").GetString(), item.GetProperty("amount").GetInt64());
    static string State(Ledger item) => JsonSerializer.Serialize(new { balances = item.Balances,
        journal = item.Journal.Select(e => new { e.From, e.To, e.Amount }), item.Version });
    public static int Main()
    {
        using var document = JsonDocument.Parse(Console.In.ReadToEnd());
        var engine = new TransferBatch();
        var observations = new List<object>();
        foreach (var operation in document.RootElement.GetProperty("batches").EnumerateArray())
        {
            var ledger = new Ledger { Version = operation.GetProperty("version").GetInt64() };
            foreach (var pair in operation.GetProperty("balances").EnumerateArray())
                ledger.Balances.Add(pair.GetProperty("key").GetString(), pair.GetProperty("value").GetInt64());
            foreach (var item in operation.GetProperty("journal").EnumerateArray()) ledger.Journal.Add(new JournalEntry(TransferOf(item)));
            var balances = ledger.Balances; var journal = ledger.Journal;
            var first = journal.Count > 0 ? journal[0] : null;
            string before = State(ledger);
            Exception error = null; long? returned = null;
            try { returned = engine.Apply(ledger, operation.GetProperty("transfers").EnumerateArray().Select(TransferOf).ToArray()); }
            catch (Exception caught) { if (!operation.GetProperty("catch_exception").GetBoolean()) throw; error = caught; }
            var available = new Dictionary<string, object> {
                ["no_exception"] = error == null,
                ["invalid_operation_exception"] = error is InvalidOperationException,
                ["overflow_exception"] = error is OverflowException,
                ["unchanged_state"] = before == State(ledger),
                ["balances_identity"] = Object.ReferenceEquals(balances, ledger.Balances),
                ["journal_identity"] = Object.ReferenceEquals(journal, ledger.Journal),
                ["first_entry_identity"] = ledger.Journal.Count > 0 && Object.ReferenceEquals(first, ledger.Journal[0]),
                ["returned_version"] = returned, ["version"] = ledger.Version, ["journal_count"] = ledger.Journal.Count };
            var row = new Dictionary<string, object>();
            foreach (var field in operation.GetProperty("observe").EnumerateArray()) row.Add(field.GetString(), available[field.GetString()]);
            if (operation.TryGetProperty("observe_balances", out var keys))
            {
                var selected = new Dictionary<string, long?>();
                foreach (var key in keys.EnumerateArray())
                    selected.Add(key.GetString(), ledger.Balances.TryGetValue(key.GetString(), out var balance) ? balance : (long?)null);
                row.Add("balances", selected);
            }
            observations.Add(row);
        }
        Console.WriteLine(JsonSerializer.Serialize(observations));
        return 0;
    }
}
