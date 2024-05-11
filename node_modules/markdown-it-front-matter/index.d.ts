declare module 'markdown-it-front-matter' {
  import MarkdownIt from 'markdown-it/lib'

  namespace markdownItFrontMatter {
    type FrontMatterPluginOptions = (rawMeta: string) => void
  }
  const markdownItFrontMatter: MarkdownIt.PluginWithOptions<markdownItFrontMatter.FrontMatterPluginOptions>
  export = markdownItFrontMatter
}
