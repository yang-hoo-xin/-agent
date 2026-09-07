// SPDX-License-Identifier: MIT
namespace OwnedConfigService
{
    public sealed class CommandResult
    {
        public string status { get; set; }
        public string key { get; set; }

        public CommandResult(string status, string key)
        {
            this.status = status;
            this.key = key;
        }
    }
}
