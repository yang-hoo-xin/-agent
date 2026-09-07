// SPDX-License-Identifier: MIT
using System;
using System.IO;
using System.Text.Json;

namespace OwnedConfigService
{
    public static class Program
    {
        public static int Main(string[] args)
        {
            if (args.Length < 2)
            {
                return Reject();
            }

            try
            {
                JsonConfigStore store = new JsonConfigStore(args[1]);
                if (args[0] == "show" && args.Length == 2)
                {
                    Console.WriteLine(JsonSerializer.Serialize(store.Read()));
                    return 0;
                }
                if (args[0] == "set" && args.Length == 4)
                {
                    using (JsonDocument parsed = JsonDocument.Parse(args[3]))
                    {
                        store.Update(args[2], parsed.RootElement);
                    }
                    Console.WriteLine(JsonSerializer.Serialize(new CommandResult("saved", args[2])));
                    return 0;
                }
                return Reject();
            }
            catch (ArgumentException)
            {
                return Reject();
            }
            catch (JsonException)
            {
                return Reject();
            }
            catch (IOException)
            {
                return Reject();
            }
        }

        private static int Reject()
        {
            Console.WriteLine(JsonSerializer.Serialize(new CommandResult("rejected", null)));
            return 2;
        }
    }
}
