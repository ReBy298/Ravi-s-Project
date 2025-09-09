partition People = m
  mode: import
  source =
    let
      Source = Sql.Databases("ENCDXPUSALT0101"),
      srcSource = Source{{[Name="Demo Tableau"]}}[Data],
      People_object = srcSource{{[Item="People",Schema="dbo"]}}[Data]
    in
      People_object
