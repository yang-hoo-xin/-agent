/* DSH 0.1.2-rc.1 client module. Only original command records drive activity. */
window.__ModuleLoader__.load({
  id: '@local/dsh-mod-agent',
  factory: () => {
    const target = 'controlled-mod-command-activity';
    const names = new Set(['mod-runs', 'mod-status', 'mod-submit', 'mod-review', 'mod-approve', 'mod-reject']);

    function createView() {
      const results = new Map();
      const snapshot = () => [...results.values()].some(Boolean);
      return {
        empty: false,
        replace({ nodes }) {
          results.clear();
          for (const node of nodes) results.set(node.key, node.data.hasResult === true);
          return snapshot();
        },
        apply({ upserts }) {
          for (const node of upserts) results.set(node.key, node.data.hasResult === true);
          return snapshot();
        },
      };
    }

    function apply(ctx) {
      ctx.uiConversation.views.register({ target, create: createView, isActive: value => value === true });
      ctx.uiConversation.events.register({
        kind: target, target,
        match(event) {
          if (event.type === 'command/run' && names.has(event.data.name)) {
            return { id: String(event.data.commandId), role: 'start' };
          }
          if (event.type === 'command/done') return { id: String(event.data.commandId), role: 'update' };
          return null;
        },
        start(_context, match) {
          return { name: match.event.data.name, hasResult: false };
        },
        update(context, match) {
          const result = match.event.data;
          return { ...context.state, hasResult: names.has(context.state.name)
            && (result.kind === 'success' || result.kind === 'error')
            && typeof result.text === 'string' && result.text.trim().length > 0 };
        },
        buildViewNode(context) {
          if (!context.start || !context.state) return null;
          return { key: context.key, kind: target, id: context.id, target,
            data: { hasResult: context.state.hasResult === true } };
        },
      });
      // This adds no tab or renderer. Once active, the official chat view still
      // renders the existing CommandNodeView and expandable command/done.text.
      ctx.uiSession.provide({ hooks: [], resolve(binding) {
        ctx.uiConversation.binding(binding).activate(target);
        return {};
      } });
    }

    return { apply, inject: ['uiConversation', 'uiSession'], createView, target };
  },
});
