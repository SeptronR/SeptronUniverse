import { EditorContent, useEditor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Bold, Italic, List, ListOrdered } from 'lucide-react';
import { Button } from '@/components/ui/Button';

/** Minimal TipTap editor (bold/italic/lists) for announcement bodies; emits HTML. */
export function RichTextEditor({ value, onChange }: { value: string; onChange: (html: string) => void }) {
  const editor = useEditor({
    extensions: [StarterKit],
    content: value,
    onUpdate: ({ editor: e }) => onChange(e.getHTML()),
  });
  if (!editor) return null;
  const tool = (label: string, Icon: typeof Bold, run: () => void, active: boolean) => (
    <Button type="button" size="icon" variant={active ? 'secondary' : 'ghost'} aria-label={label} onClick={run}>
      <Icon className="h-4 w-4" />
    </Button>
  );
  return (
    <div className="rounded-md border">
      <div className="flex gap-1 border-b p-1">
        {tool('Bold', Bold, () => editor.chain().focus().toggleBold().run(), editor.isActive('bold'))}
        {tool('Italic', Italic, () => editor.chain().focus().toggleItalic().run(), editor.isActive('italic'))}
        {tool('Bullet list', List, () => editor.chain().focus().toggleBulletList().run(), editor.isActive('bulletList'))}
        {tool('Numbered list', ListOrdered, () => editor.chain().focus().toggleOrderedList().run(), editor.isActive('orderedList'))}
      </div>
      <EditorContent editor={editor} className="prose prose-sm max-w-none p-3 [&_.ProseMirror]:min-h-[8rem] [&_.ProseMirror]:outline-none" />
    </div>
  );
}

/** Read-only rendering: the HTML is parsed through the ProseMirror schema (scripts, handlers, iframes are dropped). */
export function RichTextView({ html }: { html: string }) {
  const editor = useEditor({ extensions: [StarterKit], content: html, editable: false }, [html]);
  return <EditorContent editor={editor} className="prose prose-sm max-w-none" />;
}
