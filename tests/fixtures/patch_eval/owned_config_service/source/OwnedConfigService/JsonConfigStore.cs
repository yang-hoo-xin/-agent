// SPDX-License-Identifier: MIT
using System.Collections.Generic;
using System.IO;
using System.Text.Json;

namespace OwnedConfigService
{
    public sealed class JsonConfigStore
    {
        private readonly string path;

        public JsonConfigStore(string path)
        {
            this.path = path;
        }

        public Dictionary<string, JsonElement> Read()
        {
            if (!File.Exists(path))
            {
                return new Dictionary<string, JsonElement>();
            }
            string text = File.ReadAllText(path);
            return JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(text)
                ?? new Dictionary<string, JsonElement>();
        }

        public void Update(string key, JsonElement value)
        {
            Dictionary<string, JsonElement> configuration = Read();
            configuration[key] = value.Clone();
            Persist(configuration);
        }

        private void Persist(Dictionary<string, JsonElement> configuration)
        {
            string parent = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(parent))
            {
                Directory.CreateDirectory(parent);
            }
            string text = JsonSerializer.Serialize(configuration, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(path, text);
        }
    }
}
