partition Orders = m
  mode: import
  source =
    let
      Source = Sql.Databases("ENCDXPUSALT0101"),
      srcSource = Source{[Name="Demo Tableau"]}[Data],
      Orders_object = srcSource{[Item="Orders", Schema="dbo"]}[Data]
    in
      Orders_object
